import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

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
  /** клик по комнате (в редакторе — удаление) */
  onRoomClick?: (room: Room) => void;
  /** клик по карте в режиме рисования, [x, y] */
  onMapClick?: (point: [number, number]) => void;
  /** вершины рисуемого полигона, [x, y] */
  draft?: [number, number][];
  /** подсветить комнату (после поиска) и приблизить к ней */
  highlightRoomId?: string | null;
  /** комната в режиме правки геометрии: перетаскивание целиком и вершин */
  editRoomId?: string | null;
  /** новая геометрия правленой комнаты (после dragend) */
  onGeometryChange?: (roomId: string, geometry: Room["geometry"]) => void;
};

/**
 * Карта этажа на L.CRS.Simple: координаты — пиксели плана, [x, y] GeoJSON
 * маппится напрямую (GeoJSON [lng, lat] → Leaflet [lat, lng] = [y, x]).
 */
export default function MapView({ planUrl, rooms, onRoomClick, onMapClick, draft, highlightRoomId, editRoomId, onGeometryChange }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const overlayRef = useRef<L.ImageOverlay | null>(null);
  const roomsLayerRef = useRef<L.GeoJSON | null>(null);
  const draftLayerRef = useRef<L.LayerGroup | null>(null);
  const editLayerRef = useRef<L.LayerGroup | null>(null);
  // колбэки в ref, чтобы не пересоздавать обработчики карты при их смене
  const cbRef = useRef({ onRoomClick, onMapClick, onGeometryChange });
  useEffect(() => { cbRef.current = { onRoomClick, onMapClick, onGeometryChange }; });

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, { crs: L.CRS.Simple, minZoom: -3 });
    L.control.scale({ imperial: false }).addTo(map);
    map.on("click", (e: L.LeafletMouseEvent) => {
      cbRef.current.onMapClick?.([e.latlng.lng, e.latlng.lat]);
    });
    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; };
  }, []);

  // план: размеры берём из самого изображения (SVG без width — фолбэк 1000x1000)
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    overlayRef.current?.remove();
    overlayRef.current = null;
    if (!planUrl) { map.setView([0, 0], -1); return; }
    let cancelled = false;
    const img = new Image();
    img.onload = () => {
      // план мог смениться, пока картинка декодировалась
      if (cancelled || !mapRef.current) return;
      const w = img.naturalWidth || 1000;
      const h = img.naturalHeight || 1000;
      overlayRef.current = L.imageOverlay(planUrl, [[0, 0], [h, w]]).addTo(map);
      map.fitBounds([[0, 0], [h, w]]);
    };
    img.src = planUrl;
    return () => { cancelled = true; };
  }, [planUrl]);

  // комнаты
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    roomsLayerRef.current?.remove();
    if (rooms.length === 0) { roomsLayerRef.current = null; return; }
    const layer = L.geoJSON(
      { type: "FeatureCollection", features: rooms.map((r) => ({
        type: "Feature",
        id: r.id,
        properties: { number: r.number, name: r.name },
        geometry: r.geometry,
      })) } as GeoJSON.FeatureCollection,
      {
        style: (feature) => ({
          color: feature?.id === editRoomId ? "#f08c00" : "#1971c2",
          weight: 2,
          fillOpacity: 0.25,
        }),
        onEachFeature: (feature, lyr) => {
          lyr.bindTooltip(`${feature.properties?.number} ${feature.properties?.name ?? ""}`);
          lyr.on("click", () => {
            const room = rooms.find((r) => r.id === feature.id);
            if (room) cbRef.current.onRoomClick?.(room);
          });
        },
      },
    ).addTo(map);
    roomsLayerRef.current = layer;
  }, [rooms, editRoomId]);

  // правка геометрии: вершины-маркеры + перетаскивание полигона целиком
  useEffect(() => {
    const map = mapRef.current;
    const layer = roomsLayerRef.current;
    if (!map || !layer || !editRoomId) return;
    editLayerRef.current?.remove();
    editLayerRef.current = null;

    type Placed = L.Path & { feature?: GeoJSON.Feature };
    const lyr = layer.getLayers().find((l) => (l as Placed).feature?.id === editRoomId) as L.Polygon | undefined;
    if (!lyr) return;

    const geometryFrom = (latlngs: L.LatLng[]) => ({
      type: "Polygon" as const,
      coordinates: [latlngs.map((ll) => [Math.round(ll.lng * 100) / 100, Math.round(ll.lat * 100) / 100])],
    });

    // магнит: к вершинам соседних комнат в радиусе SNAP_PX, иначе к сетке 1px.
    // Пересечения полигонов не проверяем — снап закрывает стыковку стен,
    // произвольные наложения остаются на совести рисующего
    const SNAP_PX = 8;
    const others: [number, number][] = rooms
      .filter((r) => r.id !== editRoomId)
      .flatMap((r) => r.geometry.coordinates[0] as [number, number][]);
    const snap = (x: number, y: number): [number, number] => {
      let bx = Math.round(x), by = Math.round(y), best = SNAP_PX;
      for (const [ox, oy] of others) {
        const d = Math.hypot(ox - x, oy - y);
        if (d < best) { best = d; bx = ox; by = oy; }
      }
      return [bx, by];
    };
    const snapLatLng = (ll: L.LatLng) => {
      const [x, y] = snap(ll.lng, ll.lat);
      return L.latLng(y, x);
    };
    const group = L.layerGroup().addTo(map);
    editLayerRef.current = group;

    // вершины: GeoJSON-кольцо замкнуто (первая точка = последняя), дубликат не рисуем
    const ring = lyr.getLatLngs()[0] as L.LatLng[];
    ring.slice(0, -1).forEach((_, i) => {
      const m = L.marker(ring[i], {
        draggable: true,
        icon: L.divIcon({ className: "nv-vertex", iconSize: [12, 12] }),
      });
      m.on("drag", (e) => {
        const pts = (lyr.getLatLngs()[0] as L.LatLng[]).slice();
        const snapped = snapLatLng((e.target as L.Marker).getLatLng());
        pts[i] = snapped;
        (e.target as L.Marker).setLatLng(snapped); // маркер прилипает к сетке/вершине
        // двигаем первую вершину — тянется замыкающая
        if (i === 0) pts[pts.length - 1] = pts[0];
        lyr.setLatLngs([pts]);
      });
      m.on("dragend", () => cbRef.current.onGeometryChange?.(editRoomId, geometryFrom(lyr.getLatLngs()[0] as L.LatLng[])));
      group.addLayer(m);
    });

    // перетаскивание полигона целиком: магнит считаем по «якорной» первой вершине,
    // весь полигон сдвигается на snapped - orig — комната стыкуется углами
    let moving: { start: L.LatLng; orig: L.LatLng[] } | null = null;
    const onMove = (e: L.LeafletMouseEvent) => {
      if (!moving) return;
      const anchor = moving.orig[0];
      const target = snapLatLng(L.latLng(
        anchor.lat + e.latlng.lat - moving.start.lat,
        anchor.lng + e.latlng.lng - moving.start.lng));
      lyr.setLatLngs([moving.orig.map((ll) =>
        L.latLng(ll.lat + target.lat - anchor.lat, ll.lng + target.lng - anchor.lng))]);
    };
    const onUp = () => {
      if (!moving) return;
      moving = null;
      map.dragging.enable();
      cbRef.current.onGeometryChange?.(editRoomId, geometryFrom(lyr.getLatLngs()[0] as L.LatLng[]));
    };
    lyr.on("mousedown", (e: L.LeafletMouseEvent) => {
      moving = { start: e.latlng, orig: (lyr.getLatLngs()[0] as L.LatLng[]).map((ll) => ll.clone()) };
      map.dragging.disable(); // иначе карту тянет вместо комнаты
    });
    map.on("mousemove", onMove);
    map.on("mouseup", onUp);
    return () => {
      map.off("mousemove", onMove);
      map.off("mouseup", onUp);
      map.dragging.enable();
    };
  }, [rooms, editRoomId]);

  // превью рисуемого полигона
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    draftLayerRef.current?.remove();
    draftLayerRef.current = null;
    if (!draft || draft.length === 0) return;
    const latlngs = draft.map(([x, y]) => L.latLng(y, x));
    const group = L.layerGroup([L.polyline(draft.length >= 3 ? [...latlngs, latlngs[0]] : latlngs, { color: "#f08c00" })]).addTo(map);
    latlngs.forEach((ll) => group.addLayer(L.circleMarker(ll, { radius: 4, color: "#f08c00" })));
    draftLayerRef.current = group;
  }, [draft]);

  // подсветка после поиска
  useEffect(() => {
    const layer = roomsLayerRef.current;
    if (!layer || !highlightRoomId) return;
    type Placed = L.Path & { feature?: GeoJSON.Feature };
    const lyr = layer.getLayers().find((l) => (l as Placed).feature?.id === highlightRoomId) as L.Polygon | undefined;
    if (!lyr) return;
    layer.eachLayer((l) => (l as L.Path).setStyle(l === lyr
      ? { color: "#f08c00", fillOpacity: 0.45 }
      : { color: "#1971c2", fillOpacity: 0.25 }));
    mapRef.current?.fitBounds(lyr.getBounds(), { maxZoom: 0 });
  }, [highlightRoomId, rooms]);

  return (
    <>
      {/* маркер-вершина в режиме правки геометрии */}
      <style>{`.nv-vertex { background: #f08c00; border: 2px solid #fff; border-radius: 2px; box-shadow: 0 1px 3px rgba(0,0,0,.4); }`}</style>
      <div ref={containerRef} style={{ height: 480, border: "1px solid #dee2e6", borderRadius: 8 }} />
    </>
  );
}
