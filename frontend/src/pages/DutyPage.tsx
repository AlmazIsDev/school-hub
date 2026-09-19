import { useEffect, useMemo, useState } from "react";
import {
  Button, Card, Group, Modal, NativeSelect, Select, Stack, Table, Tabs, Text, TextInput, Title,
} from "@mantine/core";
import { apiFetch } from "../api";
import { useAuth } from "../auth";

type Zone = { id: string; name: string; created_at: string };
type Slot = { weekday: number; slot: number; user_id: string };
type Schedule = { id: string; teacher_id: string; zone_id: string; week_pattern: Slot[]; created_at: string };
type Completion = { id: string; schedule_id: string; weekday: number; slot: number; date: string; marked_at: string };
type AppUser = { id: string; full_name: string; role: string };

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const SLOTS = Array.from({ length: 8 }, (_, i) => i + 1);

export default function DutyPage() {
  const { user } = useAuth();
  const canEdit = user?.role === "teacher" || user?.role === "admin";

  return (
    <Stack gap="md">
      <Title order={1} size="h2">Дежурства</Title>
      {canEdit ? <TeacherView /> : <StudentView />}
    </Stack>
  );
}

function useApiError() {
  const [error, setError] = useState<string | null>(null);
  return { error, setError, clear: () => setError(null) };
}

function TeacherView() {
  const [zones, setZones] = useState<Zone[]>([]);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [users, setUsers] = useState<AppUser[]>([]);
  const [zoneName, setZoneName] = useState("");
  const [busy, setBusy] = useState(false);
  const { error, setError, clear } = useApiError();

  async function refresh() {
    clear();
    try {
      const [z, s, u] = await Promise.all([
        apiFetch<Zone[]>("/duty/zones"),
        apiFetch<Schedule[]>("/duty/schedules"),
        apiFetch<AppUser[]>("/users"),
      ]);
      setZones(z);
      setSchedules(s);
      setUsers(u.filter((x) => x.role === "student"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить данные");
    }
  }

  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  async function act(fn: () => Promise<unknown>, fallback: string): Promise<boolean> {
    if (busy) return false;
    setError(null);
    setBusy(true);
    try {
      await fn();
      await refresh();
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : fallback);
      return false;
    } finally {
      setBusy(false);
    }
  }

  function addZone(e: React.FormEvent) {
    e.preventDefault();
    const name = zoneName.trim();
    if (!name) return;
    act(async () => {
      await apiFetch("/duty/zones", { method: "POST", body: JSON.stringify({ name }) });
      setZoneName("");
    }, "Не удалось добавить зону");
  }

  const students = users.map((u) => ({ value: u.id, label: u.full_name }));

  return (
    <>
      {error && <div role="alert">{error}</div>}
      <Tabs defaultValue="zones">
        <Tabs.List>
          <Tabs.Tab value="zones">Зоны</Tabs.Tab>
          <Tabs.Tab value="editor">График</Tabs.Tab>
          <Tabs.Tab value="list">Графики ({schedules.length})</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="zones" pt="md">
          <Card withBorder component="form" onSubmit={addZone} maw={480}>
            <Group align="flex-end" gap="sm">
              <TextInput
                flex={1} label="Новая зона" placeholder="Спортзал, столовая…"
                value={zoneName} onChange={(e) => setZoneName(e.currentTarget.value)} maxLength={100} required
              />
              <Button type="submit" loading={busy}>Добавить</Button>
            </Group>
          </Card>
          <Table withTableBorder verticalSpacing="xs" mt="md" maw={480}>
            <Table.Thead>
              <Table.Tr><Table.Th>Зона</Table.Th><Table.Th /></Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {zones.map((z) => (
                <Table.Tr key={z.id}>
                  <Table.Td>{z.name}</Table.Td>
                  <Table.Td>
                    <Button size="xs" variant="subtle" color="red" loading={busy}
                      onClick={() => act(() => apiFetch(`/duty/zones/${z.id}`, { method: "DELETE" }), "Не удалось удалить зону")}>
                      Удалить
                    </Button>
                  </Table.Td>
                </Table.Tr>
              ))}
              {zones.length === 0 && (
                <Table.Tr><Table.Td colSpan={2} c="dimmed">Зон пока нет.</Table.Td></Table.Tr>
              )}
            </Table.Tbody>
          </Table>
        </Tabs.Panel>

        <Tabs.Panel value="editor" pt="md">
          <ScheduleEditor zones={zones} students={students} busy={busy} onSave={(body) =>
            act(() => apiFetch("/duty/schedules", { method: "POST", body: JSON.stringify(body) }), "Не удалось сохранить график")
          } />
        </Tabs.Panel>

        <Tabs.Panel value="list" pt="md">
          <Table withTableBorder verticalSpacing="xs">
            <Table.Thead>
              <Table.Tr><Table.Th>Зона</Table.Th><Table.Th>Слотов</Table.Th><Table.Th /></Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {schedules.map((s) => (
                <Table.Tr key={s.id}>
                  <Table.Td>{zones.find((z) => z.id === s.zone_id)?.name ?? s.zone_id}</Table.Td>
                  <Table.Td>{s.week_pattern.length}</Table.Td>
                  <Table.Td>
                    <Button size="xs" variant="subtle" color="red" loading={busy}
                      onClick={() => act(() => apiFetch(`/duty/schedules/${s.id}`, { method: "DELETE" }), "Не удалось удалить график")}>
                      Удалить
                    </Button>
                  </Table.Td>
                </Table.Tr>
              ))}
              {schedules.length === 0 && (
                <Table.Tr><Table.Td colSpan={3} c="dimmed">Графиков нет.</Table.Td></Table.Tr>
              )}
            </Table.Tbody>
          </Table>
        </Tabs.Panel>
      </Tabs>
    </>
  );
}

function ScheduleEditor({ zones, students, busy, onSave }: {
  zones: Zone[];
  students: { value: string; label: string }[];
  busy: boolean;
  onSave: (body: { zone_id: string; week_pattern: Slot[] }) => Promise<boolean>;
}) {
  const [zoneId, setZoneId] = useState<string | null>(null);
  const [cells, setCells] = useState<Record<string, string>>({});
  const [cell, setCell] = useState<string | null>(null);
  const [studentId, setStudentId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const byId = useMemo(() => new Map(students.map((s) => [s.value, s.label])), [students]);

  function openCell(key: string) {
    if (!zoneId) { setMsg("Сначала выбери зону"); return; }
    setMsg(null);
    setCell(key);
    setStudentId(cells[key] ?? null);
  }

  function applyCell(assign: boolean) {
    if (!cell) return;
    setCells((prev) => {
      const next = { ...prev };
      if (assign && studentId) next[cell] = studentId; else delete next[cell];
      return next;
    });
    setCell(null);
  }

  async function save() {
    if (!zoneId) { setMsg("Выбери зону"); return; }
    const week_pattern = Object.entries(cells).map(([key, uid]) => {
      const [weekday, slot] = key.split("-").map(Number);
      return { weekday, slot, user_id: uid };
    });
    if (week_pattern.length === 0) { setMsg("График пустой"); return; }
    setMsg(null);
    setSaving(true);
    try {
      if (await onSave({ zone_id: zoneId, week_pattern })) {
        setCells({});
        setMsg("График сохранён");
      }
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Не удалось сохранить график");
    } finally {
      setSaving(false);
    }
  }

  if (zones.length === 0) return <Text c="dimmed">Сначала добавь зону.</Text>;

  return (
    <Card withBorder>
      <Group align="flex-end" gap="sm" mb="md">
        <NativeSelect
          label="Зона" data={zones.map((z) => ({ value: z.id, label: z.name }))}
          value={zoneId ?? ""} onChange={(e) => { setZoneId(e.currentTarget.value); setCells({}); }}
          maw={280} required
        />
        <Button loading={busy || saving} onClick={save}>Сохранить график</Button>
        {Object.keys(cells).length > 0 && (
          <Text size="sm" c="dimmed">Назначено слотов: {Object.keys(cells).length}</Text>
        )}
      </Group>
      {msg && <div role="alert">{msg}</div>}
      <Table withTableBorder withColumnBorders verticalSpacing="xs" horizontalSpacing="xs">
        <Table.Thead>
          <Table.Tr>
            <Table.Th />
            {SLOTS.map((s) => <Table.Th key={s}>{s}</Table.Th>)}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {WEEKDAYS.map((wd, i) => (
            <Table.Tr key={wd}>
              <Table.Th>{wd}</Table.Th>
              {SLOTS.map((slot) => {
                const key = `${i + 1}-${slot}`;
                const uid = cells[key];
                return (
                  <Table.Td
                    key={slot}
                    onClick={() => openCell(key)}
                    style={{ cursor: "pointer", minWidth: 90 }}
                    title="Клик — назначить ученика"
                  >
                    {uid ? byId.get(uid) ?? uid : <Text c="dimmed" size="sm">—</Text>}
                  </Table.Td>
                );
              })}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>

      <Modal opened={cell !== null} onClose={() => setCell(null)} title="Ученик на слот" size="sm">
        <Stack>
          <Select
            data={students} placeholder="Выбери ученика" searchable
            value={studentId} onChange={setStudentId}
          />
          <Group justify="flex-end">
            <Button variant="subtle" color="red" onClick={() => applyCell(false)} disabled={!cell || !cells[cell]}>
              Очистить
            </Button>
            <Button onClick={() => applyCell(true)} disabled={!studentId}>Назначить</Button>
          </Group>
        </Stack>
      </Modal>
    </Card>
  );
}

function StudentView() {
  const [myId, setMyId] = useState<string | null>(null);
  const [zones, setZones] = useState<Zone[]>([]);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [completions, setCompletions] = useState<Completion[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function loadCompletions() {
    setCompletions(await apiFetch<Completion[]>("/duty/completions"));
  }

  useEffect(() => {
    (async () => {
      setError(null);
      try {
        const me = await apiFetch<{ id: string }>("/me");
        setMyId(me.id);
        const [z, s, c] = await Promise.all([
          apiFetch<Zone[]>("/duty/zones"),
          apiFetch<Schedule[]>(`/duty/schedules?user_id=${me.id}`),
          apiFetch<Completion[]>("/duty/completions"),
        ]);
        setZones(z);
        setSchedules(s);
        setCompletions(c);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Не удалось загрузить данные");
      }
    })();
  }, []);

  /** Отметить выполнение: сегодня, этот слот. Отметку за прошлое ставит бот. */
  const todayISO = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  };

  async function mark(c: Schedule, sl: Slot) {
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      await apiFetch("/duty/completions", {
        method: "POST",
        body: JSON.stringify({ schedule_id: c.id, weekday: sl.weekday, slot: sl.slot, date: todayISO() }),
      });
      await loadCompletions();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось отметить");
    } finally {
      setBusy(false);
    }
  }

  if (error && !myId) return <div role="alert">{error}</div>;

  return (
    <>
      {error && <div role="alert">{error}</div>}
      <Card withBorder>
        <Title order={2} size="h4" mb="md">Мои дежурства на неделю</Title>
        <Table withTableBorder verticalSpacing="xs">
          <Table.Thead>
            <Table.Tr><Table.Th>Зона</Table.Th><Table.Th>День</Table.Th><Table.Th>Слот</Table.Th><Table.Th /></Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {schedules.flatMap((s) =>
              // бэк уже фильтрует по user_id, но week_pattern могли отдать целиком — подстраховка
              s.week_pattern.filter((sl) => !myId || sl.user_id === myId).map((sl, i) => (
                <Table.Tr key={`${s.id}-${i}`}>
                  <Table.Td>{zones.find((z) => z.id === s.zone_id)?.name ?? s.zone_id}</Table.Td>
                  <Table.Td>{WEEKDAYS[sl.weekday - 1]}</Table.Td>
                  <Table.Td>{sl.slot}</Table.Td>
                  <Table.Td>
                    <Button size="xs" variant="light" disabled={busy}
                      onClick={() => mark(s, sl)}>
                      Отметить
                    </Button>
                  </Table.Td>
                </Table.Tr>
              )),
            )}
            {schedules.length === 0 && (
              <Table.Tr><Table.Td colSpan={4} c="dimmed">Слотов нет.</Table.Td></Table.Tr>
            )}
          </Table.Tbody>
        </Table>
        <Text c="dimmed" size="sm" mt="sm">«Отметить» ставит отметку за сегодня. В боте — то же самое.</Text>
      </Card>

      <Card withBorder>
        <Title order={2} size="h4" mb="md">История отметок</Title>
        <Table withTableBorder verticalSpacing="xs">
          <Table.Thead>
            <Table.Tr><Table.Th>Дата</Table.Th><Table.Th>День</Table.Th><Table.Th>Слот</Table.Th></Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {completions.map((c) => (
              <Table.Tr key={c.id}>
                <Table.Td>{c.date.slice(0, 10)}</Table.Td>
                <Table.Td>{WEEKDAYS[c.weekday - 1]}</Table.Td>
                <Table.Td>{c.slot}</Table.Td>
              </Table.Tr>
            ))}
            {completions.length === 0 && (
              <Table.Tr><Table.Td colSpan={3} c="dimmed">Отметок пока нет.</Table.Td></Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      </Card>
    </>
  );
}
