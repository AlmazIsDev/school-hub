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
};

/**
 * Карта этажа на L.CRS.Simple: координаты — пиксели плана, [x, y] GeoJSON
 * маппится напрямую (GeoJSON [lng, lat] → Leaflet [lat, lng] = [y, x]).
 */
export default function MapView({ planUrl, rooms, onRoomClick, onMapClick, draft, highlightRoomId }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const overlayRef = useRef<L.ImageOverlay | null>(null);
  const roomsLayerRef = useRef<L.GeoJSON | null>(null);
  const draftLayerRef = useRef<L.LayerGroup | null>(null);
  // колбэки в ref, чтобы не пересоздавать обработчики карты при их смене
  const cbRef = useRef({ onRoomClick, onMapClick });
  useEffect(() => { cbRef.current = { onRoomClick, onMapClick }; });

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
        style: () => ({ color: "#1971c2", weight: 2, fillOpacity: 0.25 }),
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
  }, [rooms]);

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

  return <div ref={containerRef} style={{ height: 480, border: "1px solid #dee2e6", borderRadius: 8 }} />;
}
