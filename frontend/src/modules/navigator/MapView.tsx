import { useEffect, useRef, useState } from "react";

export type Room = {
  id: string;
  floor_id: string;
  number: string;
  name: string;
  geometry: { type: string; coordinates: number[][][] };
};

type Pt = [number, number];

type Props = {
  /** objectURL плана или null */
  planUrl: string | null;
  rooms: Room[];
  /** клик по комнате */
  onRoomClick?: (room: Room) => void;
  /** клик по фону в режиме рисования, [x, y] */
  onMapClick?: (point: Pt) => void;
  /** вершины рисуемого полигона, [x, y] */
  draft?: Pt[];
  /** правка черновика: тянуть вершины, двигать полигон, ПКМ убирает точку */
  onDraftChange?: (points: Pt[]) => void;
  /** движение мыши по карте в координатах плана */
  onMouseMove?: (point: Pt) => void;
  /** резиновый прямоугольник инструмента «прямоугольник» */
  rectPreview?: { a: Pt; b: Pt } | null;
  /** подсветить комнату (после поиска), с автозумом к ней */
  highlightRoomId?: string | null;
  /** выделенная комната (клик в просмотре) */
  selectedRoomId?: string | null;
  /** комната в режиме правки геометрии: перетаскивание целиком и вершин */
  editRoomId?: string | null;
  /** новая геометрия правленой комнаты (после отпускания кнопки) */
  onGeometryChange?: (roomId: string, geometry: Room["geometry"]) => void;
  /** инкремент сбрасывает зум к плану целиком */
  resetKey?: number;
};

/** Сетка и магнит в пикселях плана: рука не рисует кривые школы. */
const GRID = 10;
const SNAP_PX = 12;

type View = { x: number; y: number; w: number; h: number };

const cross = (o: number[], a: number[], b: number[]) =>
  (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);

/** Строгая проверка пересечения отрезков ab и cd (концевые касания не считаются). */
function segmentsIntersect(a: number[], b: number[], c: number[], d: number[]): boolean {
  const d1 = cross(c, d, a), d2 = cross(c, d, b), d3 = cross(a, b, c), d4 = cross(a, b, d);
  return ((d1 > 0) !== (d2 > 0)) && ((d3 > 0) !== (d4 > 0));
}

/** ponytail: строгое сравнение не ловит наложение коллинеарных рёбер - редкий
 *  случай для точек, округлённых к сетке; если станет реальной проблемой,
 *  добавить collinear-ветку. */
export function polygonSelfIntersects(ring: number[][]): boolean {
  const closed = ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1];
  const p = closed ? ring.slice(0, -1) : ring;
  const n = p.length;
  if (n < 4) return false;
  const starts = p, ends = [...p.slice(1), p[0]];
  for (let i = 0; i < n; i++) {
    for (let j = i + 2; j < n; j++) {
      if (i === 0 && j === n - 1) continue; // соседние рёбра legitимо смыкаются
      if (segmentsIntersect(starts[i], ends[i], starts[j], ends[j])) return true;
    }
  }
  return false;
}

/**
 * Карта этажа на чистом SVG: координаты - пиксели плана, GeoJSON [x, y]
 * рисуется напрямую. Зум колесом и пан перетаскиванием - через viewBox.
 */
export default function MapView({
  planUrl, rooms, onRoomClick, onMapClick, draft, onDraftChange, onMouseMove,
  rectPreview, highlightRoomId, selectedRoomId, editRoomId, onGeometryChange, resetKey,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [planSize, setPlanSize] = useState({ w: 1000, h: 1000 });
  const [view, setView] = useState<View>({ x: 0, y: 0, w: 1000, h: 1000 });
  // геометрия (комнаты или черновика) на время драга, между pointermove и props
  const [editGeom, setEditGeom] = useState<Pt[] | null>(null);
  const [draftGeom, setDraftGeom] = useState<Pt[] | null>(null);
  const dragRef = useRef<
    | { kind: "move"; startX: number; startY: number; orig: Pt[] }
    | { kind: "draft-move"; startX: number; startY: number; orig: Pt[] }
    | { kind: "vertex"; i: number }
    | { kind: "draft-vertex"; i: number }
    | { kind: "pan"; startX: number; startY: number; orig: View; moved: boolean }
    | null
  >(null);
  const cbRef = useRef({ onRoomClick, onMapClick, onGeometryChange, onDraftChange, onMouseMove });
  useEffect(() => { cbRef.current = { onRoomClick, onMapClick, onGeometryChange, onDraftChange, onMouseMove }; });

  // размеры плана - для viewBox
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
  // при смене плана - показать его целиком
  useEffect(() => { setView({ x: 0, y: 0, w: pw, h: ph }); }, [pw, ph]);

  // зум к комнате (переход из поиска/списка)
  useEffect(() => {
    if (!highlightRoomId) return;
    const r = rooms.find((x) => x.id === highlightRoomId);
    if (!r) return;
    const ring = r.geometry.coordinates[0];
    const xs = ring.map((p) => p[0]), ys = ring.map((p) => p[1]);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
    const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
    const span = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys));
    const w = Math.min(pw, Math.max(span * 3, pw / 8));
    setView({ x: cx - w / 2, y: cy - w * (ph / pw) / 2, w, h: w * (ph / pw) });
  }, [highlightRoomId, rooms, pw, ph]);

  useEffect(() => {
    if (resetKey) setView({ x: 0, y: 0, w: pw, h: ph });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey]);

  const editing = Boolean(editRoomId && onGeometryChange);
  const draftEditable = Boolean(draft && onDraftChange);
  const showGrid = Boolean(onMapClick || editing || draftEditable);

  // вершины соседних комнат для магнита (в правке и при рисовании)
  const others: Pt[] = editing || draftEditable
    ? rooms.filter((r) => r.id !== editRoomId).flatMap((r) => r.geometry.coordinates[0] as Pt[])
    : [];

  function snap(x: number, y: number): Pt {
    let bx = Math.round(x / GRID) * GRID, by = Math.round(y / GRID) * GRID, best = SNAP_PX;
    for (const [ox, oy] of others) {
      const d = Math.hypot(ox - x, oy - y);
      if (d < best) { best = d; bx = ox; by = oy; }
    }
    return [bx, by];
  }

  function eventToPlan(e: { clientX: number; clientY: number }): Pt {
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

  // клик после пана/драга не должен ставить точку: флаг живёт до следующего pointerdown
  const panMovedRef = useRef(false);

  function onBackgroundPointerDown(e: React.PointerEvent) {
    // pointer capture на svg уводит click к svg - комната его не получит.
    // На комнате пан не начинаем: клик дойдёт до полигона (режимы «кликом»).
    if ((e.target as Element).closest(".nv-room") || (e.target as Element).closest(".nv-draft")) return;
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

  // ПКМ: убрать последнюю точку черновика (по одной, без стирания всего)
  function onContextMenu(e: React.MouseEvent) {
    e.preventDefault();
    if (!draftEditable || !draft || draft.length === 0) return;
    // contextmenu с вершины уже обработан там и сделает stopPropagation
    if (draft.length === 1) cbRef.current.onDraftChange!([]);
    else cbRef.current.onDraftChange!(draft.slice(0, -1));
    setDraftGeom(null);
  }

  function onVertexDown(kind: "vertex" | "draft-vertex") {
    return (i: number) => (e: React.PointerEvent) => {
      e.stopPropagation();
      dragRef.current = { kind, i };
      svgRef.current?.setPointerCapture(e.pointerId);
    };
  }

  // удаление вершины по ПКМ (не меньше треугольника)
  function onVertexContextMenu(ring: Pt[], i: number, apply: (pts: Pt[]) => void) {
    return (e: React.MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const closed = ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1];
      const minPts = closed ? 4 : 3;
      if (ring.length <= minPts) return;
      let pts = ring.filter((_, k) => k !== i);
      if (closed && i === 0) pts = [...pts.slice(0, -1), pts[0]];
      apply(pts);
      setEditGeom(null);
      setDraftGeom(null);
    };
  }

  function onBodyDown(kind: "move" | "draft-move", orig: Pt[]) {
    return (e: React.PointerEvent) => {
      e.stopPropagation();
      const [x, y] = eventToPlan(e);
      dragRef.current = { kind, startX: x, startY: y, orig: orig.map((p) => [...p] as Pt) };
      svgRef.current?.setPointerCapture(e.pointerId);
    };
  }

  function onPointerMove(e: React.PointerEvent) {
    const [x, y] = eventToPlan(e);
    cbRef.current.onMouseMove?.([x, y]);
    const drag = dragRef.current;
    if (!drag) return;
    if (drag.kind === "pan") {
      const dx = x - drag.startX, dy = y - drag.startY;
      if (Math.hypot(dx, dy) > 2) { drag.moved = true; panMovedRef.current = true; }
      setView({ ...drag.orig, x: drag.orig.x - dx, y: drag.orig.y - dy });
    } else if (drag.kind === "move" || drag.kind === "draft-move") {
      // и вся форма, и вершины едут по сетке (с магнитом к соседям)
      const target = snap(drag.orig[0][0] + x - drag.startX, drag.orig[0][1] + y - drag.startY);
      const dx = target[0] - drag.orig[0][0];
      const dy = target[1] - drag.orig[0][1];
      const pts = drag.orig.map(([px, py]) => [px + dx, py + dy] as Pt);
      if (drag.kind === "move") setEditGeom(pts); else setDraftGeom(pts);
    } else {
      const ring = drag.kind === "draft-vertex"
        ? (draftGeom ?? draft ?? [])
        : (editGeom ?? editedRoom?.geometry.coordinates[0] ?? []);
      const pts = ring.map((p) => [...p] as Pt);
      const [sx, sy] = snap(x, y);
      pts[drag.i] = [sx, sy];
      // замыкающая тянется с первой, но только у замкнутого контура
      const closedRing = pts.length > 1 && pts[0][0] === pts[pts.length - 1][0] && pts[0][1] === pts[pts.length - 1][1];
      if (drag.i === 0 && closedRing) pts[pts.length - 1] = [sx, sy];
      if (drag.kind === "draft-vertex") setDraftGeom(pts); else setEditGeom(pts);
    }
  }

  function onPointerUp() {
    const drag = dragRef.current;
    dragRef.current = null;
    if (!drag || drag.kind === "pan") return;
    panMovedRef.current = true; // click после драга не ставит точку рисования
    if (drag.kind === "draft-move" || drag.kind === "draft-vertex") {
      if (draftGeom) cbRef.current.onDraftChange?.(draftGeom);
      setDraftGeom(null);
      return;
    }
    if (!editGeom) return;
    cbRef.current.onGeometryChange?.(editRoomId!, {
      type: "Polygon",
      coordinates: [editGeom],
    });
    setEditGeom(null); // props обновятся из родителя той же геометрией
  }

  const editedRoom = rooms.find((r) => r.id === editRoomId) ?? null;
  const editedRing = editGeom ?? editedRoom?.geometry.coordinates[0] ?? null;
  const shownDraft = draftGeom ?? draft ?? null;

  // размеры экранного UI обратно пропорциональны зуму - на экране выглядят константно
  const labelFs = view.w / 45;
  const marker = Math.max(6, view.w / 70);

  return (
    <svg
      ref={svgRef}
      viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
      style={{ width: "100%", height: "70vh", minHeight: 480, border: "1px solid var(--mantine-color-default-border)", borderRadius: 8, background: "var(--mantine-color-body)", touchAction: "none", userSelect: "none" }}
      onClick={onBackgroundClick}
      onContextMenu={onContextMenu}
      onPointerDown={onBackgroundPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      role="img"
      aria-label="План этажа"
    >
      <style>{`.nv-room { fill-opacity: 0.35; } .nv-room:hover { fill-opacity: 0.85; }`}</style>
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
        const selected = r.id === selectedRoomId;
        const cx = ring.reduce((s, p) => s + p[0], 0) / ring.length;
        const cy = ring.reduce((s, p) => s + p[1], 0) / ring.length;
        return (
          <g key={r.id}>
            <polygon
              points={pts}
              className="nv-room"
              fill={highlighted || isEdited ? "#f08c00" : "#1971c2"}
              stroke={highlighted || isEdited ? "#f08c00" : "#1971c2"}
              strokeWidth={selected ? 5 : 2}
              vectorEffect="non-scaling-stroke"
              style={{ cursor: onRoomClick ? "pointer" : (isEdited ? "move" : "default"), ...(highlighted ? { fillOpacity: 0.55 } : {}) }}
              onClick={(e) => {
                e.stopPropagation();
                // panMovedRef тут не проверяем: пан с capture заканчивается
                // кликом на svg, до полигона он дойти не может
                cbRef.current.onRoomClick?.(r);
              }}
              onPointerDown={isEdited ? onBodyDown("move", ring as Pt[]) : undefined}
              onDoubleClick={isEdited ? (e) => {
                // вставить вершину в ближайшее ребро под курсором
                e.stopPropagation();
                const [mx, my] = eventToPlan(e);
                let bi = -1, bd = Infinity;
                for (let i = 0; i < ring.length - 1; i++) {
                  const [ax, ay] = ring[i], [bx, by] = ring[i + 1];
                  const len2 = (bx - ax) ** 2 + (by - ay) ** 2;
                  const t = len2 ? Math.max(0, Math.min(1, ((mx - ax) * (bx - ax) + (my - ay) * (by - ay)) / len2)) : 0;
                  const d = Math.hypot(ax + t * (bx - ax) - mx, ay + t * (by - ay) - my);
                  if (d < bd) { bd = d; bi = i; }
                }
                if (bi < 0) return;
                const next = ring.flatMap((p, i) => (i === bi ? [p, [Math.round(mx / GRID) * GRID, Math.round(my / GRID) * GRID] as Pt] : [p]));
                cbRef.current.onGeometryChange?.(r.id, { type: "Polygon", coordinates: [next] });
              } : undefined}
            >
              <title>{`${r.number} ${r.name}`}</title>
            </polygon>
            {r.number && (
              <text x={cx} y={cy} textAnchor="middle" fontSize={labelFs}
                fill="var(--mantine-color-text)" stroke="#fff" strokeWidth={labelFs / 8} paintOrder="stroke"
                style={{ pointerEvents: "none", fontWeight: 600 }}>
                {r.number}
              </text>
            )}
          </g>
        );
      })}

      {editedRoom && editedRing && editedRing.slice(0, -1).map(([x, y], i) => (
        <rect
          key={`v${i}`}
          x={x - marker / 2} y={y - marker / 2} width={marker} height={marker}
          fill="#f08c00" stroke="#fff" strokeWidth={2} vectorEffect="non-scaling-stroke"
          style={{ cursor: "move" }}
          onPointerDown={onVertexDown("vertex")(i)}
          onContextMenu={onVertexContextMenu(editedRing as Pt[], i, (pts) =>
            cbRef.current.onGeometryChange?.(editedRoom.id, { type: "Polygon", coordinates: [pts] }))}
        />
      ))}

      {/* середины рёбер правленой комнаты: клик добавляет вершину */}
      {editedRoom && editedRing && editedRing.slice(0, -1).map(([x, y], i) => {
        const [nx, ny] = editedRing[i + 1];
        return (
          <circle
            key={`m${i}`}
            cx={(x + nx) / 2} cy={(y + ny) / 2} r={marker / 2.5}
            fill="#fff" stroke="#f08c00" strokeWidth={2} vectorEffect="non-scaling-stroke"
            style={{ cursor: "copy" }}
            onClick={(e) => {
              e.stopPropagation();
              const next = editedRing.flatMap((p, k) => (k === i ? [p, [Math.round((x + nx) / 2 / GRID) * GRID, Math.round((y + ny) / 2 / GRID) * GRID] as Pt] : [p]));
              cbRef.current.onGeometryChange?.(editedRoom.id, { type: "Polygon", coordinates: [next] });
            }}
          />
        );
      })}

      {/* резиновый прямоугольник: без черновика, до второго клика */}
      {rectPreview && (
        <polygon
          points={[rectPreview.a, [rectPreview.b[0], rectPreview.a[1]], rectPreview.b, [rectPreview.a[0], rectPreview.b[1]]].map(([x, y]) => `${x},${y}`).join(" ")}
          fill="rgba(240,140,0,0.12)" stroke="#f08c00" strokeDasharray="6 4"
          strokeWidth={2} vectorEffect="non-scaling-stroke" style={{ pointerEvents: "none" }}
        />
      )}

      {shownDraft && shownDraft.length > 0 && (
        <g>
          <polygon
            className="nv-draft"
            points={shownDraft.map(([x, y]) => `${x},${y}`).join(" ")}
            fill="rgba(240,140,0,0.12)"
            fillOpacity={1}
            stroke="#f08c00" strokeWidth={2} vectorEffect="non-scaling-stroke"
            style={draftEditable ? { cursor: "move" } : undefined}
            onPointerDown={draftEditable ? onBodyDown("draft-move", shownDraft as Pt[]) : undefined}
          />
          {shownDraft.map(([x, y], i) => (
            <rect
              key={`d${i}`} x={x - marker / 2} y={y - marker / 2} width={marker} height={marker}
              fill="#f08c00" stroke="#fff" strokeWidth={2} vectorEffect="non-scaling-stroke"
              style={draftEditable ? { cursor: "move" } : undefined}
              onPointerDown={draftEditable ? onVertexDown("draft-vertex")(i) : undefined}
              onContextMenu={draftEditable ? onVertexContextMenu(shownDraft, i, (pts) => cbRef.current.onDraftChange?.(pts)) : undefined}
            />
          ))}
        </g>
      )}
    </svg>
  );
}
