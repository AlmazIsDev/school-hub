import { useEffect, useMemo, useState } from "react";
import {
  Button, Card, Group, Modal, NativeSelect, NumberInput, Pagination, Stack, Table, Text,
  TextInput, Title, Textarea,
} from "@mantine/core";
import { apiFetch } from "../api";

type SchoolClass = { id: string; grade: number; letter: string };
type AppUser = {
  id: string; login: string; full_name: string; role: string;
  class_id: string | null; vk_id: number | null;
};

const ROLE_LABEL: Record<string, string> = {
  student: "ученик", teacher: "учитель", admin: "админ",
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
  const [createError, setCreateError] = useState<string | null>(null);

  // редактирование пользователя
  const [editUser, setEditUser] = useState<AppUser | null>(null);
  const [editFullName, setEditFullName] = useState("");
  const [editRole, setEditRole] = useState("student");
  const [editClassId, setEditClassId] = useState<string | null>(null);

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
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : fallback);
      return false;
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
    setCreateError(null);
    act(async () => {
      try {
        const res = await apiFetch<{ temp_password: string }>("/users", {
          method: "POST",
          body: JSON.stringify({ login: login.trim(), full_name: fullName.trim(), role, class_id: role === "student" ? classId : null }),
        });
        setTempPassword(res.temp_password);
        setLogin("");
        setFullName("");
        setClassId(null);
      } catch (err) {
        // ошибка именно у формы: сверху страницы её легко пропустить
        setCreateError(err instanceof Error ? err.message : "Не удалось создать пользователя");
      }
    }, "Не удалось создать пользователя");
  };

  function openEditUser(u: AppUser) {
    setEditUser(u);
    setEditFullName(u.full_name);
    setEditRole(u.role);
    setEditClassId(u.class_id);
  }

  const saveUser = () =>
    act(async () => {
      await apiFetch(`/users/${editUser!.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          full_name: editFullName.trim(),
          role: editRole,
          class_id: editRole === "student" ? editClassId : null,
        }),
      });
      setEditUser(null);
    }, "Не удалось сохранить пользователя");

  const deleteUser = (u: AppUser) => {
    if (!window.confirm(`Удалить пользователя ${u.full_name} (${u.login})?`)) return;
    act(() => apiFetch(`/users/${u.id}`, { method: "DELETE" }), "Не удалось удалить");
  };

  const resetPassword = (u: AppUser) => {
    if (!window.confirm(`Сбросить пароль ${u.full_name}? Будет выдан временный.`)) return;
    act(async () => {
      const res = await apiFetch<{ temp_password: string }>(`/users/${u.id}/reset-password`, { method: "POST" });
      setTempPassword(res.temp_password);
    }, "Не удалось сбросить пароль");
  };

  const unlinkVk = (u: AppUser) => {
    if (!window.confirm(`Отвязать VK у ${u.full_name}?`)) return;
    act(() => apiFetch(`/users/${u.id}/vk`, { method: "DELETE" }), "Не удалось отвязать VK");
  };

  const deleteClass = (c: SchoolClass) => {
    if (!window.confirm(`Удалить класс ${c.grade}«${c.letter}»?`)) return;
    act(() => apiFetch(`/classes/${c.id}`, { method: "DELETE" }), "Не удалось удалить класс");
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
            {createError && <div role="alert">{createError}</div>}
            {tempPassword && (
              <Text c="red" fw={500}>Временный пароль (покажется один раз): <Text span style={{ userSelect: "all" }}>{tempPassword}</Text></Text>
            )}
          </Stack>
        </Card>
      </Group>

      <Card withBorder>
        <Title order={2} size="h3" mb="md">Классы</Title>
        <Table withTableBorder verticalSpacing="xs" maw={560}>
          <Table.Thead><Table.Tr><Table.Th>Класс</Table.Th><Table.Th>Учеников</Table.Th><Table.Th /></Table.Tr></Table.Thead>
          <Table.Tbody>
            {classes.map((c) => (
              <Table.Tr key={c.id}>
                <Table.Td>{c.grade}«{c.letter}»</Table.Td>
                <Table.Td>{users.filter((u) => u.class_id === c.id).length}</Table.Td>
                <Table.Td>
                  <Button size="xs" variant="subtle" color="red" loading={busy} onClick={() => deleteClass(c)}>
                    Удалить
                  </Button>
                </Table.Td>
              </Table.Tr>
            ))}
            {classes.length === 0 && <Table.Tr><Table.Td colSpan={3} c="dimmed">Классов пока нет.</Table.Td></Table.Tr>}
          </Table.Tbody>
        </Table>
      </Card>

      <Card withBorder>
        <Title order={2} size="h3" mb="md">Пользователи</Title>
        <Table withTableBorder verticalSpacing="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Логин</Table.Th><Table.Th>ФИО</Table.Th><Table.Th>Роль</Table.Th>
              <Table.Th>Класс</Table.Th><Table.Th>VK</Table.Th><Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {users.map((u) => (
              <Table.Tr key={u.id}>
                <Table.Td>{u.login}</Table.Td>
                <Table.Td>{u.full_name}</Table.Td>
                <Table.Td>{ROLE_LABEL[u.role] ?? u.role}</Table.Td>
                <Table.Td>{u.class_id ? classById.get(u.class_id) ?? "?" : "—"}</Table.Td>
                <Table.Td>{u.vk_id != null ? "привязан" : "—"}</Table.Td>
                <Table.Td>
                  <Group gap="xs">
                    <Button size="xs" variant="light" onClick={() => openEditUser(u)}>Изменить</Button>
                    <Button size="xs" variant="light" onClick={() => resetPassword(u)}>Сбросить пароль</Button>
                    {u.vk_id != null && (
                      <Button size="xs" variant="light" color="red" onClick={() => unlinkVk(u)}>Отвязать VK</Button>
                    )}
                    <Button size="xs" variant="subtle" color="red" onClick={() => deleteUser(u)}>Удалить</Button>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
            {users.length === 0 && <Table.Tr><Table.Td colSpan={6} c="dimmed">Пользователей нет.</Table.Td></Table.Tr>}
          </Table.Tbody>
        </Table>
      </Card>

      <DbManager />

      <Modal opened={editUser !== null} onClose={() => setEditUser(null)} title={`Редактирование: ${editUser?.login ?? ""}`}>
        <Stack gap="sm">
          <TextInput label="ФИО" value={editFullName} onChange={(e) => setEditFullName(e.currentTarget.value)} maxLength={200} />
          <NativeSelect
            label="Роль"
            data={Object.entries(ROLE_LABEL).map(([value, label]) => ({ value, label }))}
            value={editRole}
            onChange={(e) => { setEditRole(e.currentTarget.value); setEditClassId(null); }}
          />
          {editRole === "student" && (
            <NativeSelect
              label="Класс"
              data={[{ value: "", label: "Без класса" }, ...classOptions]}
              value={editClassId ?? ""}
              onChange={(e) => setEditClassId(e.currentTarget.value || null)}
            />
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setEditUser(null)}>Отмена</Button>
            <Button onClick={saveUser} loading={busy}>Сохранить</Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}

// ---------- прямое управление БД ----------

type DbCollection = { name: string; count: number };
type DbDocs = { items: Record<string, unknown>[]; total: number; has_more: boolean };
// значения приходят в Extended JSON: {"$oid": "..."} / {"$date": "..."}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type DbDoc = Record<string, any>;

const DB_PAGE_SIZE = 20;

function docPreview(doc: DbDoc): string {
  return Object.entries(doc)
    .filter(([k]) => k !== "_id")
    .map(([k, v]) => `${k}: ${shortVal(v)}`)
    .join("  ·  ");
}

function shortVal(v: unknown): string {
  if (v === null) return "null";
  if (typeof v === "boolean" || typeof v === "number") return String(v);
  if (typeof v === "string") return `"${v}"`;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const o = v as Record<string, any>;
  if (o && o.$oid) return String(o.$oid);
  if (o && o.$date) return typeof o.$date === "string" ? o.$date : JSON.stringify(o.$date);
  return JSON.stringify(v);
}

function DbManager() {
  const [collections, setCollections] = useState<DbCollection[]>([]);
  const [name, setName] = useState("");
  const [docs, setDocs] = useState<DbDocs | null>(null);
  const [page, setPage] = useState(0);
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<{ id: string | null; text: string } | null>(null);
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadCollections() {
    try {
      const list = await apiFetch<DbCollection[]>("/admin/db/collections");
      setCollections(list);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка загрузки коллекций");
    }
  }

  useEffect(() => { loadCollections(); }, []);

  useEffect(() => {
    if (!name) return;
    loadDocs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, page, query]);

  async function loadDocs() {
    setError(null);
    try {
      const params = new URLSearchParams({ skip: String(page * DB_PAGE_SIZE), limit: String(DB_PAGE_SIZE) });
      if (query.trim()) params.set("q", query.trim());
      setDocs(await apiFetch<DbDocs>(`/admin/db/${name}/docs?${params}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка загрузки документов");
    }
  }

  function reload() {
    loadDocs();
    loadCollections();
  }

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  const saveDoc = () =>
    run(async () => {
      let parsed;
      try {
        parsed = JSON.parse(editing!.text);
      } catch (err) {
        setJsonError(`Невалидный JSON: ${err instanceof Error ? err.message : ""}`);
        return;
      }
      setJsonError(null);
      if (editing!.id) {
        await apiFetch(`/admin/db/${name}/${editing!.id}`, { method: "PUT", body: JSON.stringify(parsed) });
      } else {
        await apiFetch(`/admin/db/${name}`, { method: "POST", body: JSON.stringify(parsed) });
      }
      setEditing(null);
      reload();
    });

  const deleteDoc = (id: string) => {
    if (!window.confirm("Удалить документ?")) return;
    run(async () => {
      await apiFetch(`/admin/db/${name}/${id}`, { method: "DELETE" });
      reload();
    });
  };

  const totalPages = docs ? Math.max(1, Math.ceil(docs.total / DB_PAGE_SIZE)) : 1;

  return (
    <Card withBorder>
      <Title order={2} size="h3" mb="md">База данных</Title>
      {error && <div role="alert">{error}</div>}
      <Group gap="sm" mb="md">
        <NativeSelect
          label="Коллекция"
          data={collections.map((c) => ({ value: c.name, label: `${c.name} (${c.count})` }))}
          value={name}
          onChange={(e) => { setName(e.currentTarget.value); setPage(0); }}
          maw={280}
        />
        <TextInput
          label="Поиск" placeholder="текст или поле: значение" maw={320}
          value={query}
          onChange={(e) => { setQuery(e.currentTarget.value); setPage(0); }}
        />
        <Button variant="light" onClick={() => { setEditing({ id: null, text: "{\n  \n}" }); setJsonError(null); }}>
          Новый документ
        </Button>
      </Group>

      {docs && (
        <Table withTableBorder verticalSpacing="xs">
          <Table.Thead><Table.Tr><Table.Th>Документ</Table.Th><Table.Th w={160} /></Table.Tr></Table.Thead>
          <Table.Tbody>
            {docs.items.map((d) => {
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              const id = (d._id as any)?.$oid as string;
              return (
                <Table.Tr key={id}>
                  <Table.Td style={{ wordBreak: "break-all" }}>
                    <Text size="xs">{docPreview(d)}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4} wrap="nowrap">
                      <Button size="compact-xs" variant="light"
                        onClick={() => { setEditing({ id, text: JSON.stringify(d, null, 2) }); setJsonError(null); }}>
                        Изменить
                      </Button>
                      <Button size="compact-xs" variant="subtle" color="red" onClick={() => deleteDoc(id)}>
                        Удалить
                      </Button>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              );
            })}
            {docs.items.length === 0 && (
              <Table.Tr><Table.Td colSpan={2} c="dimmed">Документов нет.</Table.Td></Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      )}

      {docs && docs.total > DB_PAGE_SIZE && (
        <Group justify="space-between" mt="sm">
          <Text size="sm" c="dimmed">Всего: {docs.total}</Text>
          <Pagination total={totalPages} value={page + 1} onChange={(p) => setPage(p - 1)} />
        </Group>
      )}

      <Modal opened={editing !== null} onClose={() => setEditing(null)}
        title={editing?.id ? "Правка документа" : "Новый документ"} size="lg">
        <Stack gap="sm">
          <Textarea
            value={editing?.text ?? ""}
            onChange={(e) => {
              // currentTarget обнуляется после обработчика — читаем значение сразу
              const text = e.currentTarget.value;
              setEditing((cur) => (cur ? { ...cur, text } : cur));
            }}
            minRows={12}
            styles={{ input: { fontFamily: "monospace", fontSize: 13 } }}
          />
          {jsonError && <div role="alert">{jsonError}</div>}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setEditing(null)}>Отмена</Button>
            <Button onClick={saveDoc} loading={busy}>Сохранить</Button>
          </Group>
        </Stack>
      </Modal>
    </Card>
  );
}
