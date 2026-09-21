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

/**
 * Карта этажа на чистом SVG: координаты — пиксели плана, GeoJSON [x, y]
 * рисуется напрямую. Вся картина масштабируется под контейнер.
 */
export default function MapView({ planUrl, rooms, onRoomClick, onMapClick, draft, highlightRoomId, editRoomId, onGeometryChange }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [planSize, setPlanSize] = useState({ w: 1000, h: 1000 });
  // геометрия редактируемой комнаты на время драга, между pointermove и обновлением props
  const [editGeom, setEditGeom] = useState<number[][] | null>(null);
  const dragRef = useRef<
    | { kind: "move"; startX: number; startY: number; orig: number[][] }
    | { kind: "vertex"; i: number }
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

  const { w, h } = planSize;
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

  function clientToPlan(e: React.PointerEvent | React.MouseEvent): [number, number] {
    const svg = svgRef.current!;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM()!.inverse());
    return [p.x, p.y];
  }

  function onBackgroundClick(e: React.MouseEvent) {
    if (!cbRef.current.onMapClick) return;
    const [x, y] = clientToPlan(e);
    // рисование по сетке: клик прилипает сразу
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
    const [x, y] = clientToPlan(e);
    dragRef.current = { kind: "move", startX: x, startY: y, orig };
    svgRef.current?.setPointerCapture(e.pointerId);
  }

  function onPointerMove(e: React.PointerEvent) {
    const drag = dragRef.current;
    if (!drag) return;
    const [x, y] = clientToPlan(e);
    if (drag.kind === "move") {
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
    if (!drag || !editGeom) return;
    cbRef.current.onGeometryChange?.(editRoomId!, {
      type: "Polygon",
      coordinates: [editGeom],
    });
    setEditGeom(null); // props обновятся из родителя той же геометрией
  }

  const editedRoom = rooms.find((r) => r.id === editRoomId) ?? null;
  const editedRing = editGeom ?? editedRoom?.geometry.coordinates[0] ?? null;

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${w} ${h}`}
      style={{ width: "100%", height: 480, border: "1px solid #dee2e6", borderRadius: 8, background: "#fff", touchAction: "none", userSelect: "none" }}
      onClick={onBackgroundClick}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      role="img"
      aria-label="План этажа"
    >
      {planUrl && (
        <image href={planUrl} x={0} y={0} width={w} height={h} preserveAspectRatio="none" />
      )}

      {showGrid && (
        <>
          {/* сетка тонкая + жирная линия каждые 5 клеток, чтобы масштаб читался */}
          <defs>
            <pattern id="nv-grid" width={GRID} height={GRID} patternUnits="userSpaceOnUse">
              <path d={`M ${GRID} 0 L 0 0 0 ${GRID}`} fill="none" stroke="#e7e7e7" strokeWidth="1" />
            </pattern>
            <pattern id="nv-grid5" width={GRID * 5} height={GRID * 5} patternUnits="userSpaceOnUse">
              <rect width={GRID * 5} height={GRID * 5} fill="url(#nv-grid)" />
              <path d={`M ${GRID * 5} 0 L 0 0 0 ${GRID * 5}`} fill="none" stroke="#c9c9c9" strokeWidth="1.5" />
            </pattern>
          </defs>
          <rect x={0} y={0} width={w} height={h} fill="url(#nv-grid5)" />
        </>
      )}

      {rooms.map((r) => {
        const isEdited = r.id === editRoomId;
        const ring = isEdited && editedRing ? editedRing : r.geometry.coordinates[0];
        const pts = ring.map(([x, y]) => `${x},${y}`).join(" ");
        const highlighted = r.id === highlightRoomId;
        return (
          <polygon
            key={r.id}
            points={pts}
            fill={highlighted || isEdited ? "#f08c00" : "#1971c2"}
            fillOpacity={highlighted ? 0.45 : 0.25}
            stroke={highlighted || isEdited ? "#f08c00" : "#1971c2"}
            strokeWidth={2}
            style={{ cursor: onRoomClick ? "pointer" : "default" }}
            onClick={(e) => {
              e.stopPropagation();
              cbRef.current.onRoomClick?.(r);
            }}
            onPointerDown={isEdited ? onRoomBodyDown : undefined}
          >
            <title>{`${r.number} ${r.name}`}</title>
          </polygon>
        );
      })}

      {editedRoom && editedRing && (
        <g>
          {editedRing.slice(0, -1).map(([x, y], i) => (
            <rect
              key={i}
              x={x - 5} y={y - 5} width={10} height={10}
              fill="#f08c00" stroke="#fff" strokeWidth={2}
              style={{ cursor: "move" }}
              onPointerDown={onVertexDown(i)}
            />
          ))}
        </g>
      )}

      {draft && draft.length > 0 && (
        <g>
          <polygon
            points={draft.map(([x, y]) => `${x},${y}`).join(" ")}
            fill="none" stroke="#f08c00" strokeWidth={2}
          />
          {draft.map(([x, y], i) => (
            <rect key={i} x={x - 3} y={y - 3} width={6} height={6} fill="#f08c00" />
          ))}
        </g>
      )}
    </svg>
  );
}
