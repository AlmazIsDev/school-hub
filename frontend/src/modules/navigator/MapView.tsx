import { useEffect, useRef, useState } from "react";

export type Room = {
  id: string;
  floor_id: string;
  number: string;
  name: string;
  geometry: { type: string; coordinates: number[][][] };
};

type Props = {
  /** objectURL плана или null */
  planUrl: string | null;
  rooms: Room[];
  /** клик по комнате */
  onRoomClick?: (room: Room) => void;
  /** клик по фону в режиме рисования, [x, y] */
  onMapClick?: (point: [number, number]) => void;
  /** вершины рисуемого полигона, [x, y] */
  draft?: [number, number][];
  /** подсветить комнату (после поиска) */
  highlightRoomId?: string | null;
  /** комната в режиме правки геометрии: перетаскивание целиком и вершин */
  editRoomId?: string | null;
  /** новая геометрия правленой комнаты (после отпускания кнопки) */
  onGeometryChange?: (roomId: string, geometry: Room["geometry"]) => void;
};

/** Сетка и магнит в пикселях плана: рука не рисует кривые школы. */
const GRID = 10;
const SNAP_PX = 12;

type View = { x: number; y: number; w: number; h: number };

/**
 * Карта этажа на чистом SVG: координаты — пиксели плана, GeoJSON [x, y]
 * рисуется напрямую. Зум колесом и пан перетаскиванием — через viewBox.
 */
export default function MapView({ planUrl, rooms, onRoomClick, onMapClick, draft, highlightRoomId, editRoomId, onGeometryChange }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [planSize, setPlanSize] = useState({ w: 1000, h: 1000 });
  const [view, setView] = useState<View>({ x: 0, y: 0, w: 1000, h: 1000 });
  // геометрия редактируемой комнаты на время драга, между pointermove и обновлением props
  const [editGeom, setEditGeom] = useState<number[][] | null>(null);
  const dragRef = useRef<
    | { kind: "move"; startX: number; startY: number; orig: number[][] }
    | { kind: "vertex"; i: number }
    | { kind: "pan"; startX: number; startY: number; orig: View; moved: boolean }
    | null
  >(null);
  const cbRef = useRef({ onRoomClick, onMapClick, onGeometryChange });
  useEffect(() => { cbRef.current = { onRoomClick, onMapClick, onGeometryChange }; });

  // размеры плана — для viewBox
  useEffect(() => {
    if (!planUrl) { setPlanSize({ w: 1000, h: 1000 }); return; }
    let cancelled = false;
    const img = new Image();
    img.onload = () => {
      if (cancelled) return;
      setPlanSize({ w: img.naturalWidth || 1000, h: img.naturalHeight || 1000 });
    };
    img.src = planUrl;
    return () => { cancelled = true; };
  }, [planUrl]);

  const { w: pw, h: ph } = planSize;
  // при смене плана — показать его целиком
  useEffect(() => { setView({ x: 0, y: 0, w: pw, h: ph }); }, [pw, ph]);

  const editing = Boolean(editRoomId && onGeometryChange);
  const showGrid = Boolean(onMapClick || editing);

  // вершины соседних комнат для магнита (только в режиме правки)
  const others: [number, number][] = editing
    ? rooms.filter((r) => r.id !== editRoomId).flatMap((r) => r.geometry.coordinates[0] as [number, number][])
    : [];

  function snap(x: number, y: number): [number, number] {
    let bx = Math.round(x / GRID) * GRID, by = Math.round(y / GRID) * GRID, best = SNAP_PX;
    for (const [ox, oy] of others) {
      const d = Math.hypot(ox - x, oy - y);
      if (d < best) { best = d; bx = ox; by = oy; }
    }
    return [bx, by];
  }

  function eventToPlan(e: { clientX: number; clientY: number }): [number, number] {
    const svg = svgRef.current!;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM()!.inverse());
    return [p.x, p.y];
  }

  // зум колесом к точке под курсором; нативный листенер, т.к. React onWheel пассивный
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const [mx, my] = eventToPlan(e);
      setView((v) => {
        const minW = pw / 40, maxW = pw * 1.5;
        const nw = Math.min(maxW, Math.max(minW, v.w * (e.deltaY > 0 ? 1.2 : 1 / 1.2)));
        const k = nw / v.w;
        return { w: nw, h: v.h * k, x: mx - (mx - v.x) * k, y: my - (my - v.y) * k };
      });
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, [pw, ph]);

  // клик после пана не должен ставить точку рисования: флаг живёт до следующего pointerdown
  const panMovedRef = useRef(false);

  function onBackgroundPointerDown(e: React.PointerEvent) {
    // фон: пан всегда, рисование — по клику без сдвига (см. onBackgroundClick)
    panMovedRef.current = false;
    const [x, y] = eventToPlan(e);
    dragRef.current = { kind: "pan", startX: x, startY: y, orig: view, moved: false };
    svgRef.current?.setPointerCapture(e.pointerId);
  }

  function onBackgroundClick(e: React.MouseEvent) {
    if (panMovedRef.current) return;
    if (!cbRef.current.onMapClick) return;
    const [x, y] = eventToPlan(e);
    cbRef.current.onMapClick([Math.round(x / GRID) * GRID, Math.round(y / GRID) * GRID]);
  }

  function onVertexDown(i: number) {
    return (e: React.PointerEvent) => {
      e.stopPropagation();
      dragRef.current = { kind: "vertex", i };
      svgRef.current?.setPointerCapture(e.pointerId);
    };
  }

  function onRoomBodyDown(e: React.PointerEvent) {
    if (!editing) return;
    e.stopPropagation();
    const orig = (editGeom ?? editedRoom?.geometry.coordinates[0] ?? []).map((p) => [...p]);
    const [x, y] = eventToPlan(e);
    dragRef.current = { kind: "move", startX: x, startY: y, orig };
    svgRef.current?.setPointerCapture(e.pointerId);
  }

  function onPointerMove(e: React.PointerEvent) {
    const drag = dragRef.current;
    if (!drag) return;
    const [x, y] = eventToPlan(e);
    if (drag.kind === "pan") {
      const dx = x - drag.startX, dy = y - drag.startY;
      if (Math.hypot(dx, dy) > 2) { drag.moved = true; panMovedRef.current = true; }
      setView({ ...drag.orig, x: drag.orig.x - dx, y: drag.orig.y - dy });
    } else if (drag.kind === "move") {
      const target = snap(drag.orig[0][0] + x - drag.startX, drag.orig[0][1] + y - drag.startY);
      const dx = target[0] - drag.orig[0][0];
      const dy = target[1] - drag.orig[0][1];
      setEditGeom(drag.orig.map(([px, py]) => [px + dx, py + dy]));
    } else {
      const ring = editGeom ?? editedRoom?.geometry.coordinates[0] ?? [];
      const pts = ring.map((p) => [...p]);
      const [sx, sy] = snap(x, y);
      pts[drag.i] = [sx, sy];
      if (drag.i === 0) pts[pts.length - 1] = [sx, sy]; // замыкающая тянется с первой
      setEditGeom(pts);
    }
  }

  function onPointerUp() {
    const drag = dragRef.current;
    dragRef.current = null;
    if (!drag || drag.kind === "pan") return;
    if (!editGeom) return;
    cbRef.current.onGeometryChange?.(editRoomId!, {
      type: "Polygon",
      coordinates: [editGeom],
    });
    setEditGeom(null); // props обновятся из родителя той же геометрией
  }

  const editedRoom = rooms.find((r) => r.id === editRoomId) ?? null;
  const editedRing = editGeom ?? editedRoom?.geometry.coordinates[0] ?? null;

  // размеры экранного UI обратно пропорциональны зуму — на экране выглядят константно
  const labelFs = view.w / 45;
  const marker = Math.max(6, view.w / 70);

  return (
    <svg
      ref={svgRef}
      viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
      style={{ width: "100%", height: "70vh", minHeight: 480, border: "1px solid #dee2e6", borderRadius: 8, background: "#fff", touchAction: "none", userSelect: "none" }}
      onClick={onBackgroundClick}
      onPointerDown={onBackgroundPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      role="img"
      aria-label="План этажа"
    >
      <style>{`.nv-room:hover { fill-opacity: 0.4; }`}</style>
      <defs>
        <pattern id="nv-grid" width={GRID} height={GRID} patternUnits="userSpaceOnUse">
          <path d={`M ${GRID} 0 L 0 0 0 ${GRID}`} fill="none" stroke="#e7e7e7" strokeWidth="1" />
        </pattern>
        <pattern id="nv-grid5" width={GRID * 5} height={GRID * 5} patternUnits="userSpaceOnUse">
          <rect width={GRID * 5} height={GRID * 5} fill="url(#nv-grid)" />
          <path d={`M ${GRID * 5} 0 L 0 0 0 ${GRID * 5}`} fill="none" stroke="#c9c9c9" strokeWidth="1.5" />
        </pattern>
      </defs>

      {planUrl && <image href={planUrl} x={0} y={0} width={pw} height={ph} preserveAspectRatio="none" />}
      {showGrid && <rect x={0} y={0} width={pw} height={ph} fill="url(#nv-grid5)" />}

      {rooms.map((r) => {
        const isEdited = r.id === editRoomId;
        const ring = isEdited && editedRing ? editedRing : r.geometry.coordinates[0];
        const pts = ring.map(([x, y]) => `${x},${y}`).join(" ");
        const highlighted = r.id === highlightRoomId;
        const cx = ring.reduce((s, p) => s + p[0], 0) / ring.length;
        const cy = ring.reduce((s, p) => s + p[1], 0) / ring.length;
        return (
          <g key={r.id}>
            <polygon
              points={pts}
              className="nv-room"
              fill={highlighted || isEdited ? "#f08c00" : "#1971c2"}
              fillOpacity={highlighted ? 0.45 : undefined}
              stroke={highlighted || isEdited ? "#f08c00" : "#1971c2"}
              strokeWidth={2}
              vectorEffect="non-scaling-stroke"
              style={{ cursor: onRoomClick ? "pointer" : (isEdited ? "move" : "default") }}
              onClick={(e) => {
                e.stopPropagation();
                if (panMovedRef.current) return;
                cbRef.current.onRoomClick?.(r);
              }}
              onPointerDown={isEdited ? onRoomBodyDown : undefined}
            >
              <title>{`${r.number} ${r.name}`}</title>
            </polygon>
            {r.number && (
              <text x={cx} y={cy} textAnchor="middle" fontSize={labelFs}
                fill="#1c2a3a" stroke="#fff" strokeWidth={labelFs / 8} paintOrder="stroke"
                style={{ pointerEvents: "none", fontWeight: 600 }}>
                {r.number}
              </text>
            )}
          </g>
        );
      })}

      {editedRoom && editedRing && editedRing.slice(0, -1).map(([x, y], i) => (
        <rect
          key={i}
          x={x - marker / 2} y={y - marker / 2} width={marker} height={marker}
          fill="#f08c00" stroke="#fff" strokeWidth={2} vectorEffect="non-scaling-stroke"
          style={{ cursor: "move" }}
          onPointerDown={onVertexDown(i)}
        />
      ))}

      {draft && draft.length > 0 && (
        <g>
          <polygon
            points={draft.map(([x, y]) => `${x},${y}`).join(" ")}
            fill="none" stroke="#f08c00" strokeWidth={2} vectorEffect="non-scaling-stroke"
          />
          {draft.map(([x, y], i) => (
            <rect key={i} x={x - marker / 2} y={y - marker / 2} width={marker} height={marker} fill="#f08c00" />
          ))}
        </g>
      )}
    </svg>
  );
}
