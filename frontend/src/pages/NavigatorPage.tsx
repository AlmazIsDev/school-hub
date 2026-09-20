import { useEffect, useRef, useState } from "react";
import {
  Button, Card, Group, Modal, NativeSelect, NumberInput, Stack, Table, Tabs, Text, TextInput, Title,
} from "@mantine/core";
import { apiBlob, apiFetch } from "../api";
import { useAuth } from "../auth";
import MapView, { type Room } from "../modules/navigator/MapView";

type Building = { id: string; name: string; address: string };
type Floor = { id: string; building_id: string; level: number; plan_id: string | null };
type SearchResult = { id: string; number: string; name: string; floor_id: string; building_id: string | null };

function errMsg(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback;
}

/** Загружает план с Authorization и отдаёт objectURL; вызывает revoke у предыдущего. */
function usePlanObjectUrl(planId: string | null | undefined) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setError(null);
    if (!planId) { setUrl(null); return; }
    let cancelled = false;
    let objectUrl: string | null = null;
    apiBlob(`/nav/plans/${planId}`)
      .then((b) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(b);
        setUrl(objectUrl);
      })
      .catch((err) => { if (!cancelled) setError(errMsg(err, "Не удалось загрузить план")); });
    return () => {
      // отменяем и поздний резолв, и утечку objectURL при размонтировании/смене плана
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      setUrl(null);
    };
  }, [planId]);
  return { url, error };
}

export default function NavigatorPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [buildings, setBuildings] = useState<Building[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function loadBuildings() {
    try { setBuildings(await apiFetch<Building[]>("/nav/buildings")); }
    catch (err) { setError(errMsg(err, "Не удалось загрузить здания")); }
  }
  useEffect(() => { loadBuildings(); }, []);

  return (
    <Stack gap="md">
      <Title order={1} size="h2">Карта школы</Title>
      {error && <div role="alert">{error}</div>}
      <Tabs defaultValue="map" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="map">Просмотр</Tabs.Tab>
          {isAdmin && <Tabs.Tab value="editor">Редактор</Tabs.Tab>}
        </Tabs.List>
        <Tabs.Panel value="map" pt="md">
          <Viewer buildings={buildings} />
        </Tabs.Panel>
        {isAdmin && (
          <Tabs.Panel value="editor" pt="md">
            <Editor buildings={buildings} reloadBuildings={loadBuildings} />
          </Tabs.Panel>
        )}
      </Tabs>
    </Stack>
  );
}

// ---------- просмотр ----------

function Viewer({ buildings }: { buildings: Building[] }) {
  const [buildingId, setBuildingId] = useState<string | null>(null);
  const [floors, setFloors] = useState<Floor[]>([]);
  const [floorId, setFloorId] = useState<string | null>(null);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [selectedRoom, setSelectedRoom] = useState<Room | null>(null);
  const [highlightRoomId, setHighlightRoomId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { url: planUrl, error: planError } = usePlanObjectUrl(
    floors.find((f) => f.id === floorId)?.plan_id,
  );
  // этаж, выбранный при переходе из поиска, применяется после загрузки этажей здания
  const pendingFloorRef = useRef<string | null>(null);

  useEffect(() => {
    if (!buildingId) { setFloors([]); setFloorId(null); return; }
    apiFetch<Floor[]>(`/nav/floors?building_id=${buildingId}`)
      .then((f) => {
        setFloors(f);
        const pending = pendingFloorRef.current;
        pendingFloorRef.current = null;
        setFloorId(pending && f.some((x) => x.id === pending) ? pending : f[0]?.id ?? null);
      })
      .catch((err) => setError(errMsg(err, "Не удалось загрузить этажи")));
  }, [buildingId]);

  useEffect(() => {
    if (!floorId) { setRooms([]); return; }
    apiFetch<Room[]>(`/nav/rooms?floor_id=${floorId}`)
      .then(setRooms)
      .catch((err) => setError(errMsg(err, "Не удалось загрузить комнаты")));
  }, [floorId]);

  async function search(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    setError(null);
    try { setResults(await apiFetch<SearchResult[]>(`/nav/search?q=${encodeURIComponent(q)}`)); }
    catch (err) { setError(errMsg(err, "Поиск не удался")); }
  }

  function goToRoom(r: SearchResult) {
    setResults(null);
    setQuery("");
    setSelectedRoom(null);
    setHighlightRoomId(null);
    if (r.building_id && r.building_id !== buildingId) {
      pendingFloorRef.current = r.floor_id;
      setBuildingId(r.building_id);
    } else {
      setFloorId(r.floor_id);
    }
    setHighlightRoomId(r.id);
  }

  const currentFloor = floors.find((f) => f.id === floorId);

  return (
    <Stack gap="md">
      <Group align="flex-end" gap="sm">
        <NativeSelect
          label="Здание" maw={280}
          data={buildings.map((b) => ({ value: b.id, label: b.name }))}
          value={buildingId ?? ""}
          onChange={(e) => { setBuildingId(e.currentTarget.value || null); setHighlightRoomId(null); setSelectedRoom(null); }}
          disabled={buildings.length === 0}
        />
        <NativeSelect
          label="Этаж" maw={160}
          data={floors.map((f) => ({ value: f.id, label: `Этаж ${f.level}` }))}
          value={floorId ?? ""}
          onChange={(e) => { setFloorId(e.currentTarget.value || null); setHighlightRoomId(null); setSelectedRoom(null); }}
          disabled={floors.length === 0}
        />
        <form onSubmit={search} style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
          <TextInput
            label="Поиск" placeholder="Кабинет…" maw={200} value={query}
            onChange={(e) => setQuery(e.currentTarget.value)} maxLength={64}
          />
          <Button type="submit" variant="light">Найти</Button>
        </form>
      </Group>

      {error && <div role="alert">{error}</div>}
      {planError && <div role="alert">{planError}</div>}

      {results && (
        <Card withBorder padding="xs">
          {results.length === 0 && <Text c="dimmed">Ничего не найдено.</Text>}
          {results.map((r) => (
            <Text key={r.id} component="a" onClick={() => goToRoom(r)} c="blue" style={{ cursor: "pointer" }}>
              {r.number} {r.name && <span>— {r.name}</span>}
            </Text>
          ))}
        </Card>
      )}

      {!currentFloor ? (
        <Text c="dimmed">Выбери здание и этаж.</Text>
      ) : (
        <Group align="flex-start" gap="md">
          <div style={{ flex: 1, minWidth: 320 }}>
            {currentFloor.plan_id
              ? <MapView planUrl={planUrl} rooms={rooms} highlightRoomId={highlightRoomId}
                  onRoomClick={setSelectedRoom} />
              : <Text c="dimmed">План не загружен.</Text>}
          </div>
          {selectedRoom && (
            <Card withBorder w={240}>
              <Title order={3} size="h4">Кабинет {selectedRoom.number}</Title>
              {selectedRoom.name && <Text>{selectedRoom.name}</Text>}
            </Card>
          )}
        </Group>
      )}
    </Stack>
  );
}

// ---------- редактор ----------

function Editor({ buildings, reloadBuildings }: { buildings: Building[]; reloadBuildings: () => Promise<void> }) {
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [buildingId, setBuildingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // переименование здания
  const [renaming, setRenaming] = useState<Building | null>(null);
  const [rnName, setRnName] = useState("");
  const [rnAddress, setRnAddress] = useState("");

  async function act(fn: () => Promise<unknown>, fallback: string): Promise<boolean> {
    if (busy) return false;
    setError(null);
    setBusy(true);
    try { await fn(); return true; }
    catch (err) { setError(errMsg(err, fallback)); return false; }
    finally { setBusy(false); }
  }

  async function addBuilding(e: React.FormEvent) {
    e.preventDefault();
    if (await act(
      () => apiFetch("/nav/buildings", { method: "POST", body: JSON.stringify({ name: name.trim(), address: address.trim() }) }),
      "Не удалось добавить здание",
    )) { setName(""); setAddress(""); await reloadBuildings(); }
  }

  function openRename(b: Building) {
    setRenaming(b);
    setRnName(b.name);
    setRnAddress(b.address);
  }

  const saveRename = () =>
    act(async () => {
      await apiFetch(`/nav/buildings/${renaming!.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name: rnName.trim(), address: rnAddress.trim() }),
      });
      setRenaming(null);
      await reloadBuildings();
    }, "Не удалось переименовать здание");

  return (
    <Stack gap="md">
      <Card withBorder component="form" onSubmit={addBuilding} maw={520}>
        <Group align="flex-end" gap="sm">
          <TextInput flex={1} label="Новое здание" placeholder="Основной корпус"
            value={name} onChange={(e) => setName(e.currentTarget.value)} maxLength={200} required />
          <TextInput flex={1} label="Адрес" placeholder="ул. Школьная, 1"
            value={address} onChange={(e) => setAddress(e.currentTarget.value)} maxLength={200} required />
          <Button type="submit" loading={busy}>Добавить</Button>
        </Group>
      </Card>

      {buildings.length === 0 ? (
        <Text c="dimmed">Сначала добавь здание.</Text>
      ) : (
        <>
          <Group align="flex-end" gap="sm">
            <NativeSelect
              label="Здание" maw={280}
              data={buildings.map((b) => ({ value: b.id, label: b.name }))}
              value={buildingId ?? ""}
              onChange={(e) => setBuildingId(e.currentTarget.value || null)}
            />
            <Button variant="light" disabled={!buildingId}
              onClick={() => openRename(buildings.find((b) => b.id === buildingId)!)}>
              Переименовать
            </Button>
            <Button variant="light" color="red" loading={busy}
              disabled={!buildingId}
              onClick={() => act(async () => {
                await apiFetch(`/nav/buildings/${buildingId}`, { method: "DELETE" });
                setBuildingId(null);
                await reloadBuildings();
              }, "Не удалось удалить здание")}>
              Удалить здание
            </Button>
          </Group>
          {error && <div role="alert">{error}</div>}
          {buildingId && <FloorsEditor buildingId={buildingId} act={act} busy={busy} />}

          <Modal opened={renaming !== null} onClose={() => setRenaming(null)} title="Переименование здания">
            <Stack gap="sm">
              <TextInput label="Название" value={rnName} onChange={(e) => setRnName(e.currentTarget.value)} maxLength={200} required />
              <TextInput label="Адрес" value={rnAddress} onChange={(e) => setRnAddress(e.currentTarget.value)} maxLength={200} required />
              <Group justify="flex-end">
                <Button variant="default" onClick={() => setRenaming(null)}>Отмена</Button>
                <Button onClick={saveRename} loading={busy}>Сохранить</Button>
              </Group>
            </Stack>
          </Modal>
        </>
      )}
    </Stack>
  );
}

type Act = (fn: () => Promise<unknown>, fallback: string) => Promise<boolean>;

function FloorsEditor({ buildingId, act, busy }: { buildingId: string; act: Act; busy: boolean }) {
  const [floors, setFloors] = useState<Floor[]>([]);
  const [level, setLevel] = useState<string | number>(1);
  const [floorId, setFloorId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try { setFloors(await apiFetch<Floor[]>(`/nav/floors?building_id=${buildingId}`)); }
    catch (err) { setError(errMsg(err, "Не удалось загрузить этажи")); }
  }
  useEffect(() => { setFloorId(null); refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [buildingId]);

  async function addFloor(e: React.FormEvent) {
    e.preventDefault();
    if (await act(
      () => apiFetch("/nav/floors", { method: "POST", body: JSON.stringify({ building_id: buildingId, level: Number(level) }) }),
      "Не удалось добавить этаж",
    )) await refresh();
  }

  return (
    <Stack gap="md">
      <Card withBorder component="form" onSubmit={addFloor} maw={420}>
        <Group align="flex-end" gap="sm">
          <NumberInput label="Новый этаж" value={level} onChange={setLevel} min={-5} max={50} required w={140} />
          <Button type="submit" loading={busy}>Добавить</Button>
        </Group>
      </Card>
      {error && <div role="alert">{error}</div>}
      <Table withTableBorder verticalSpacing="xs" maw={520}>
        <Table.Thead>
          <Table.Tr><Table.Th>Этаж</Table.Th><Table.Th>План</Table.Th><Table.Th /></Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {floors.map((f) => (
            <Table.Tr key={f.id}>
              <Table.Td>{f.level}</Table.Td>
              <Table.Td>{f.plan_id ? "загружен" : "нет"}</Table.Td>
              <Table.Td>
                <Group gap="xs">
                  <Button size="xs" variant="light" onClick={() => setFloorId(f.id === floorId ? null : f.id)}>
                    {f.id === floorId ? "Закрыть" : "Редактировать"}
                  </Button>
                  <Button size="xs" variant="subtle" color="red"
                    onClick={async () => {
                      if (await act(() => apiFetch(`/nav/floors/${f.id}`, { method: "DELETE" }), "Не удалось удалить этаж")) await refresh();
                    }}>
                    Удалить
                  </Button>
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
          {floors.length === 0 && <Table.Tr><Table.Td colSpan={3} c="dimmed">Этажей пока нет.</Table.Td></Table.Tr>}
        </Table.Tbody>
      </Table>
      {floorId && <FloorEditor key={floorId} floor={floors.find((f) => f.id === floorId)!} act={act} busy={busy} refreshFloors={refresh} />}
    </Stack>
  );
}

function FloorEditor({ floor, act, busy, refreshFloors }: { floor: Floor; act: Act; busy: boolean; refreshFloors: () => Promise<void> }) {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [drawing, setDrawing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [geometryMode, setGeometryMode] = useState(false);
  const [geometryRoomId, setGeometryRoomId] = useState<string | null>(null);
  const [geometryDirty, setGeometryDirty] = useState(false);
  const [editingRoomMode, setEditingRoomMode] = useState(false);
  const [editingRoom, setEditingRoom] = useState<Room | null>(null);
  const [draft, setDraft] = useState<[number, number][]>([]);
  const [roomNumber, setRoomNumber] = useState("");
  const [roomName, setRoomName] = useState("");
  const [finishOpen, setFinishOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { url: planUrl, error: planError } = usePlanObjectUrl(floor.plan_id);

  async function refresh() {
    try { setRooms(await apiFetch<Room[]>(`/nav/rooms?floor_id=${floor.id}`)); }
    catch (err) { setError(errMsg(err, "Не удалось загрузить комнаты")); }
  }
  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [floor.id]);

  async function uploadPlan(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.currentTarget.files?.[0];
    e.currentTarget.value = "";
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    if (await act(() => apiFetch(`/nav/floors/${floor.id}/plan`, { method: "POST", body: fd }), "Не удалось загрузить план")) {
      // plan_id после загрузки новый — обновляем список этажей, FloorEditor перезапустится по key
      await refreshFloors();
    }
  }

  function onMapClick(point: [number, number]) {
    if (!drawing || finishOpen) return;
    setDraft((d) => [...d, point]);
  }

  async function onRoomClick(room: Room) {
    if (deleting) {
      if (!window.confirm(`Удалить кабинет ${room.number}?`)) return;
      if (await act(() => apiFetch(`/nav/rooms/${room.id}`, { method: "DELETE" }), "Не удалось удалить комнату")) await refresh();
      return;
    }
    if (geometryMode) {
      setGeometryRoomId(room.id === geometryRoomId ? null : room.id);
      setGeometryDirty(false);
      return;
    }
    if (editingRoomMode) {
      setEditingRoom(room);
      setRoomNumber(room.number);
      setRoomName(room.name);
    }
  }

  async function saveRoom(e: React.FormEvent) {
    e.preventDefault();
    if (draft.length < 3) return;
    if (await act(
      () => apiFetch("/nav/rooms", {
        method: "POST",
        body: JSON.stringify({
          floor_id: floor.id, number: roomNumber.trim(), name: roomName.trim(),
          geometry: { type: "Polygon", coordinates: [[...draft, draft[0]]] },
        }),
      }),
      "Не удалось сохранить комнату",
    )) {
      setDraft([]); setRoomNumber(""); setRoomName(""); setFinishOpen(false); setDrawing(false);
      await refresh();
    }
  }

  return (
    <Card withBorder>
      <Group gap="sm" mb="md">
        <Button variant={drawing ? "filled" : "light"} onClick={() => { setDrawing(!drawing); setDeleting(false); setDraft([]); setFinishOpen(false); }}>
          {drawing ? "Режим рисования: вкл" : "Добавить комнату"}
        </Button>
        <Button variant={deleting ? "filled" : "light"} color="red" onClick={() => { setDeleting(!deleting); setDrawing(false); setEditingRoomMode(false); setDraft([]); }}>
          {deleting ? "Режим удаления: вкл" : "Удалять комнаты кликом"}
        </Button>
        <Button variant={editingRoomMode ? "filled" : "light"} onClick={() => { setEditingRoomMode(!editingRoomMode); setDrawing(false); setDeleting(false); setGeometryMode(false); setDraft([]); }}>
          {editingRoomMode ? "Режим правки: вкл" : "Править комнаты кликом"}
        </Button>
        <Button variant={geometryMode ? "filled" : "light"} onClick={() => { setGeometryMode(!geometryMode); setDrawing(false); setDeleting(false); setEditingRoomMode(false); setDraft([]); setGeometryRoomId(null); setGeometryDirty(false); }}>
          {geometryMode ? "Режим геометрии: вкл" : "Двигать/править форму"}
        </Button>
        <Button component="label" variant="light">
          {floor.plan_id ? "Заменить план" : "Загрузить план"}
          <input type="file" accept=".svg,.png,.jpg,.jpeg,image/svg+xml,image/png,image/jpeg" hidden onChange={uploadPlan} />
        </Button>
        {drawing && (
          <>
            <Text size="sm">Точек: {draft.length}</Text>
            <Button disabled={draft.length < 3 || finishOpen} onClick={() => setFinishOpen(true)}>Завершить</Button>
            <Button variant="subtle" color="red" onClick={() => setDraft([])}>Отмена</Button>
          </>
        )}
      </Group>

      {error && <div role="alert">{error}</div>}
      {planError && <div role="alert">{planError}</div>}

      {finishOpen ? (
        <Card withBorder component="form" onSubmit={saveRoom} mb="md" maw={420}>
          <Group align="flex-end" gap="sm">
            <TextInput flex={1} label="Номер кабинета" value={roomNumber}
              onChange={(e) => setRoomNumber(e.currentTarget.value)} maxLength={32} required />
            <TextInput flex={1} label="Название" value={roomName}
              onChange={(e) => setRoomName(e.currentTarget.value)} maxLength={200} />
            <Button type="submit" loading={busy}>Сохранить</Button>
            <Button variant="subtle" onClick={() => setFinishOpen(false)}>Назад</Button>
          </Group>
        </Card>
      ) : (
        <MapView
          planUrl={planUrl}
          rooms={rooms}
          onRoomClick={onRoomClick}
          onMapClick={onMapClick}
          draft={drawing ? draft : undefined}
          editRoomId={geometryRoomId}
          onGeometryChange={(roomId, geometry) => {
            setRooms((rs) => rs.map((r) => (r.id === roomId ? { ...r, geometry } : r)));
            setGeometryDirty(true);
          }}
        />
      )}
      {drawing && !finishOpen && <Text size="sm" c="dimmed" mt="xs">Кликай по карте, чтобы ставить вершины полигона.</Text>}

      {geometryMode && (
        geometryRoomId ? (
          <Group gap="sm" mt="xs">
            <Button
              disabled={!geometryDirty}
              loading={busy}
              onClick={async () => {
                const room = rooms.find((r) => r.id === geometryRoomId)!;
                if (await act(() =>
                  apiFetch(`/nav/rooms/${room.id}`, {
                    method: "PUT",
                    body: JSON.stringify({
                      floor_id: floor.id, number: room.number, name: room.name,
                      geometry: room.geometry,
                    }),
                  }), "Не удалось сохранить геометрию")) {
                  setGeometryDirty(false);
                }
              }}
            >
              Сохранить геометрию
            </Button>
            <Button variant="subtle" onClick={async () => { setGeometryRoomId(null); setGeometryDirty(false); await refresh(); }}>
              Отменить правки
            </Button>
          </Group>
        ) : (
          <Text size="sm" c="dimmed" mt="xs">
            Кликни по комнате, затем тяни её целиком или за вершины. Изменения применяются после «Сохранить».
          </Text>
        )
      )}

      <Modal opened={editingRoom !== null} onClose={() => setEditingRoom(null)} title={`Кабинет ${editingRoom?.number ?? ""}`}>
        <Stack gap="sm">
          <TextInput label="Номер" value={roomNumber} onChange={(e) => setRoomNumber(e.currentTarget.value)} maxLength={32} required />
          <TextInput label="Название" value={roomName} onChange={(e) => setRoomName(e.currentTarget.value)} maxLength={200} />
          <Text size="sm" c="dimmed">
            Форму и положение меняет режим «Двигать/править форму».
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setEditingRoom(null)}>Отмена</Button>
            <Button
              loading={busy}
              onClick={() =>
                act(async () => {
                  await apiFetch(`/nav/rooms/${editingRoom!.id}`, {
                    method: "PUT",
                    body: JSON.stringify({
                      floor_id: floor.id,
                      number: roomNumber.trim(),
                      name: roomName.trim(),
                      geometry: editingRoom!.geometry,
                    }),
                  });
                  setEditingRoom(null);
                  await refresh();
                }, "Не удалось сохранить комнату")
              }
            >
              Сохранить
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Card>
  );
}
