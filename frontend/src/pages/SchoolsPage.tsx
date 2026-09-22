import { useEffect, useState } from "react";
import {
  Button, Card, Group, Stack, Table, Text, TextInput, Title,
} from "@mantine/core";
import { apiFetch } from "../api";

type School = { id: string; name: string; code: string };

export default function SchoolsPage() {
  const [schools, setSchools] = useState<School[]>([]);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [adminLogin, setAdminLogin] = useState("");
  const [adminFullName, setAdminFullName] = useState("");
  const [tempPassword, setTempPassword] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setSchools(await apiFetch<School[]>("/schools"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка загрузки");
    }
  }

  useEffect(() => { load(); }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await apiFetch<{ admin_temp_password: string }>("/schools", {
        method: "POST",
        body: JSON.stringify({ name, code, admin_login: adminLogin, admin_full_name: adminFullName }),
      });
      setTempPassword(res.admin_temp_password);
      setName(""); setCode(""); setAdminLogin(""); setAdminFullName("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка создания");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    if (!confirm("Удалить школу?")) return;
    try {
      await apiFetch(`/schools/${id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка удаления");
    }
  }

  return (
    <Stack gap="lg">
      <Title order={2}>Школы</Title>
      {error && <div role="alert">{error}</div>}

      <Card withBorder component="form" onSubmit={create}>
        <Stack gap="sm">
          <Text fw={600}>Новая школа</Text>
          <Group grow>
            <TextInput label="Название" value={name} onChange={(e) => setName(e.currentTarget.value)} required />
            <TextInput label="Код (латиницей)" value={code} onChange={(e) => setCode(e.currentTarget.value)} required />
          </Group>
          <Group grow>
            <TextInput label="Логин админа" value={adminLogin} onChange={(e) => setAdminLogin(e.currentTarget.value)} required />
            <TextInput label="ФИО админа" value={adminFullName} onChange={(e) => setAdminFullName(e.currentTarget.value)} required />
          </Group>
          <Button type="submit" loading={busy} w={200}>Создать</Button>
          {tempPassword && (
            <Text c="red">Временный пароль админа (покажите один раз): <b>{tempPassword}</b></Text>
          )}
        </Stack>
      </Card>

      <Table variant="outlined">
        <Table.Thead>
          <Table.Tr><Table.Th>Название</Table.Th><Table.Th>Код</Table.Th><Table.Th /></Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {schools.map((s) => (
            <Table.Tr key={s.id}>
              <Table.Td>{s.name}</Table.Td>
              <Table.Td>{s.code}</Table.Td>
              <Table.Td>
                <Button variant="subtle" color="red" size="compact-sm" onClick={() => remove(s.id)}>
                  Удалить
                </Button>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}
