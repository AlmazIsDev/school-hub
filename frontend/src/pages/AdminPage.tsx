import { useEffect, useMemo, useState } from "react";
import {
  Button, Card, Group, NativeSelect, NumberInput, Stack, Table, Text,
  TextInput, Title,
} from "@mantine/core";
import { apiFetch } from "../api";

type SchoolClass = { id: string; grade: number; letter: string };
type AppUser = { id: string; login: string; full_name: string; role: string; class_id: string | null; vk_id: number | null };

const ROLE_LABEL: Record<string, string> = {
  student: "ученик",
  teacher: "учитель",
  admin: "админ",
};

export default function AdminPage() {
  const [classes, setClasses] = useState<SchoolClass[]>([]);
  const [users, setUsers] = useState<AppUser[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // класс
  const [grade, setGrade] = useState<string | number>(1);
  const [letter, setLetter] = useState("");

  // пользователь
  const [login, setLogin] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState("student");
  const [classId, setClassId] = useState<string | null>(null);
  const [tempPassword, setTempPassword] = useState<string | null>(null);

  async function refresh() {
    setError(null);
    try {
      const [c, u] = await Promise.all([
        apiFetch<SchoolClass[]>("/classes"),
        apiFetch<AppUser[]>("/users"),
      ]);
      setClasses(c);
      setUsers(u);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить данные");
    }
  }

  useEffect(() => { refresh(); }, []);

  async function act(fn: () => Promise<unknown>, fallback: string) {
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      await fn();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : fallback);
    } finally {
      setBusy(false);
    }
  }

  const addClass = (e: React.FormEvent) => {
    e.preventDefault();
    act(async () => {
      await apiFetch("/classes", { method: "POST", body: JSON.stringify({ grade: Number(grade), letter: letter.trim() }) });
      setLetter("");
    }, "Не удалось добавить класс");
  };

  const createUser = (e: React.FormEvent) => {
    e.preventDefault();
    act(async () => {
      const res = await apiFetch<{ temp_password: string }>("/users", {
        method: "POST",
        body: JSON.stringify({ login: login.trim(), full_name: fullName.trim(), role, class_id: role === "student" ? classId : null }),
      });
      setTempPassword(res.temp_password);
      setLogin("");
      setFullName("");
      setClassId(null);
    }, "Не удалось создать пользователя");
  };

  const classById = useMemo(() => new Map(classes.map((c) => [c.id, `${c.grade}«${c.letter}»`])), [classes]);
  const classOptions = classes.map((c) => ({ value: c.id, label: `${c.grade}«${c.letter}»` }));

  return (
    <Stack gap="md">
      <Title order={1} size="h2">Администрирование</Title>
      {error && <div role="alert">{error}</div>}

      <Group align="flex-start" gap="md">
        <Card withBorder component="form" onSubmit={addClass} w={320}>
          <Stack gap="sm">
            <Title order={2} size="h3">Новый класс</Title>
            <Group align="flex-end" gap="xs">
              <NumberInput label="Параллель" value={grade} onChange={setGrade} min={1} max={11} required w={120} />
              <TextInput label="Буква" value={letter} onChange={(e) => setLetter(e.currentTarget.value)} maxLength={2} required w={100} />
              <Button type="submit" loading={busy}>Добавить</Button>
            </Group>
          </Stack>
        </Card>

        <Card withBorder component="form" onSubmit={createUser} w={480}>
          <Stack gap="sm">
            <Title order={2} size="h3">Новый пользователь</Title>
            <TextInput label="Логин" value={login} onChange={(e) => setLogin(e.currentTarget.value)} maxLength={64} required />
            <TextInput label="ФИО" value={fullName} onChange={(e) => setFullName(e.currentTarget.value)} maxLength={200} required />
            <NativeSelect
              label="Роль"
              data={Object.entries(ROLE_LABEL).map(([value, label]) => ({ value, label }))}
              value={role}
              onChange={(e) => { setRole(e.currentTarget.value); setClassId(null); }}
            />
            {role === "student" && (
              <NativeSelect
                label="Класс"
                data={[{ value: "", label: "Без класса" }, ...classOptions]}
                value={classId ?? ""}
                onChange={(e) => setClassId(e.currentTarget.value || null)}
              />
            )}
            <Button type="submit" loading={busy}>Создать</Button>
            {tempPassword && (
              <Text c="red" fw={500}>Временный пароль (покажется один раз): <Text span style={{ userSelect: "all" }}>{tempPassword}</Text></Text>
            )}
          </Stack>
        </Card>
      </Group>

      <Card withBorder>
        <Title order={2} size="h3" mb="md">Классы</Title>
        <Table withTableBorder verticalSpacing="xs" maw={480}>
          <Table.Thead><Table.Tr><Table.Th>Класс</Table.Th><Table.Th>Учеников</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {classes.map((c) => (
              <Table.Tr key={c.id}>
                <Table.Td>{c.grade}«{c.letter}»</Table.Td>
                <Table.Td>{users.filter((u) => u.class_id === c.id).length}</Table.Td>
              </Table.Tr>
            ))}
            {classes.length === 0 && <Table.Tr><Table.Td colSpan={2} c="dimmed">Классов пока нет.</Table.Td></Table.Tr>}
          </Table.Tbody>
        </Table>
      </Card>

      <Card withBorder>
        <Title order={2} size="h3" mb="md">Пользователи</Title>
        <Table withTableBorder verticalSpacing="xs">
          <Table.Thead>
            <Table.Tr><Table.Th>Логин</Table.Th><Table.Th>ФИО</Table.Th><Table.Th>Роль</Table.Th><Table.Th>Класс</Table.Th><Table.Th>VK</Table.Th></Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {users.map((u) => (
              <Table.Tr key={u.id}>
                <Table.Td>{u.login}</Table.Td>
                <Table.Td>{u.full_name}</Table.Td>
                <Table.Td>{ROLE_LABEL[u.role] ?? u.role}</Table.Td>
                <Table.Td>{u.class_id ? classById.get(u.class_id) ?? "?" : "—"}</Table.Td>
                <Table.Td>{u.vk_id != null ? "привязан" : "—"}</Table.Td>
              </Table.Tr>
            ))}
            {users.length === 0 && <Table.Tr><Table.Td colSpan={5} c="dimmed">Пользователей нет.</Table.Td></Table.Tr>}
          </Table.Tbody>
        </Table>
      </Card>
    </Stack>
  );
}
