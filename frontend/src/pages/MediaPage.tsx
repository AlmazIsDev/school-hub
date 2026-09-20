import { useEffect, useMemo, useState } from "react";
import {
  Badge, Button, Card, Group, Modal, Select, Stack, Table, Tabs, Text, Textarea, TextInput, Title,
} from "@mantine/core";
import { apiFetch } from "../api";
import { useAuth } from "../auth";

type PostStatus = "idea" | "in_progress" | "review" | "published";

type Post = {
  id: string;
  title: string;
  body: string;
  status: PostStatus;
  assignee_id: string | null;
  publish_at: string | null;
  created_at: string;
};

type Idea = {
  id: string;
  author_id: string;
  text: string;
  status: "new" | "accepted" | "rejected";
  created_at: string;
};

type UserRow = { id: string; full_name: string; role: string };

const CHAIN: PostStatus[] = ["idea", "in_progress", "review", "published"];

const COLUMN: Record<PostStatus, { label: string; color: string }> = {
  idea: { label: "Идеи", color: "gray" },
  in_progress: { label: "В работе", color: "blue" },
  review: { label: "На проверке", color: "yellow" },
  published: { label: "Опубликованы", color: "green" },
};

const MONTHS = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];

/** date-инпут даёт "YYYY-MM-DD" — бэкодному datetime его хватает. */
function toDateInput(iso: string | null): string {
  return iso ? iso.slice(0, 10) : "";
}

// Мини-markdown без зависимости: **жирный**, *курсив*, `код`, [текст](url).
// Сначала экранируем HTML, потом вставляем разметку — XSS-безопасно.
function renderMarkdown(src: string): string {
  const esc = src
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const md = esc
    .replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>")
    .replace(/\*([^*\n]+)\*/g, "<i>$1</i>")
    .replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return md;
}

function PostBody({ text }: { text: string }) {
  return (
    <div style={{ whiteSpace: "pre-wrap" }}
      dangerouslySetInnerHTML={{ __html: renderMarkdown(text) }} />
  );
}

export default function MediaPage() {
  const { user } = useAuth();
  const canManage = user?.role === "teacher" || user?.role === "admin";

  const [posts, setPosts] = useState<Post[]>([]);
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // создание поста
  const [newTitle, setNewTitle] = useState("");
  const [newBody, setNewBody] = useState("");

  // ученик: предложить тему
  const [ideaText, setIdeaText] = useState("");

  // календарь
  const [month, setMonth] = useState(() => {
    const d = new Date();
    return { y: d.getFullYear(), m: d.getMonth() };
  });
  const [selectedPostId, setSelectedPostId] = useState<string | null>(null);

  // редактирование поста
  const [editing, setEditing] = useState<Post | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editBody, setEditBody] = useState("");
  const [editAssignee, setEditAssignee] = useState<string | null>(null);
  const [editPublishAt, setEditPublishAt] = useState("");

  useEffect(() => {
    refresh();
    if (canManage) {
      apiFetch<Idea[]>("/media/ideas").then(setIdeas).catch(() => {});
      apiFetch<UserRow[]>("/users").then(setUsers).catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refresh() {
    setError(null);
    try {
      setPosts(await apiFetch<Post[]>("/media/posts"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить посты");
    }
  }

  async function run(fn: () => Promise<unknown>) {
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      await fn();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  const createPost = (e: React.FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await apiFetch("/media/posts", {
        method: "POST",
        body: JSON.stringify({ title: newTitle, body: newBody }),
      });
      setNewTitle("");
      setNewBody("");
    });
  };

  const movePost = (p: Post) =>
    run(() =>
      apiFetch(`/media/posts/${p.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: CHAIN[CHAIN.indexOf(p.status) + 1] }),
      }));

  const suggestIdea = (e: React.FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await apiFetch("/media/ideas", { method: "POST", body: JSON.stringify({ text: ideaText }) });
      setIdeaText("");
    });
  };

  const actOnIdea = (idea: Idea, action: "accept" | "reject") =>
    run(async () => {
      await apiFetch(`/media/ideas/${idea.id}/${action}`, { method: "POST" });
      setIdeas((list) => list.filter((i) => i.id !== idea.id));
    });

  function openEdit(p: Post) {
    setEditing(p);
    setEditTitle(p.title);
    setEditBody(p.body);
    setEditAssignee(p.assignee_id);
    setEditPublishAt(toDateInput(p.publish_at));
  }

  const saveEdit = () =>
    run(async () => {
      if (!editing) return;
      await apiFetch(`/media/posts/${editing.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          title: editTitle,
          body: editBody,
          assignee_id: editAssignee,
          publish_at: editPublishAt
            ? new Date(editPublishAt + "T12:00:00").toISOString()
            : null,
        }),
      });
      setEditing(null);
    });

  const userById = useMemo(() => new Map(users.map((u) => [u.id, u])), [users]);

  // сетка месяца: понедельник — первый день
  const calendarCells = useMemo(() => {
    const first = new Date(month.y, month.m, 1);
    const daysInMonth = new Date(month.y, month.m + 1, 0).getDate();
    const lead = (first.getDay() + 6) % 7;
    const cells: (number | null)[] = Array(lead).fill(null);
    for (let d = 1; d <= daysInMonth; d++) cells.push(d);
    while (cells.length % 7 !== 0) cells.push(null);
    return cells;
  }, [month]);

  const monthPosts = useMemo(() => {
    const map = new Map<number, Post[]>();
    for (const p of posts) {
      if (!p.publish_at) continue;
      const d = new Date(p.publish_at);
      if (d.getFullYear() === month.y && d.getMonth() === month.m) {
        map.set(d.getDate(), [...(map.get(d.getDate()) ?? []), p]);
      }
    }
    return map;
  }, [posts, month]);

  const assigneeOptions = users.map((u) => ({ value: u.id, label: u.full_name || u.role }));

  function card(p: Post, col: PostStatus) {
    const selected = p.id === selectedPostId;
    return (
      <Card key={p.id} withBorder padding="xs" mb="xs"
        style={selected ? { borderColor: "var(--mantine-color-blue-6)" } : undefined}>
        <Group justify="space-between" gap="xs" wrap="nowrap">
          <Text fw={500} size="sm" style={{ cursor: "pointer" }} onClick={() => setSelectedPostId(p.id)}>
            {p.title}
          </Text>
          <Group gap={4} wrap="nowrap">
            {col !== "published" && (
              <Button size="compact-xs" variant="default" aria-label={`Перевести «${p.title}» далее`} disabled={busy}
                onClick={() => movePost(p)}>→</Button>
            )}
          </Group>
        </Group>
        <Text size="xs" c="dimmed" lineClamp={2}>{p.body}</Text>
        <Group justify="space-between" mt={4}>
          <Text size="xs" c="dimmed">
            {p.assignee_id ? `Ответственный: ${userById.get(p.assignee_id)?.full_name ?? "?"}` : ""}
          </Text>
          <Button size="compact-xs" variant="subtle" onClick={() => openEdit(p)}>Изменить</Button>
        </Group>
        {p.publish_at && (
          <Text size="xs" c="dimmed">К публикации: {new Date(p.publish_at).toLocaleDateString("ru-RU")}</Text>
        )}
      </Card>
    );
  }

  const newIdeas = ideas.filter((i) => i.status === "new");
  const published = posts.filter((p) => p.status === "published");

  return (
    <Stack gap="md">
      <Title order={1} size="h2">Медиацентр</Title>
      {error && <div role="alert">{error}</div>}

      {canManage ? (
        <Tabs defaultValue="board">
          <Tabs.List>
            <Tabs.Tab value="board">Редакция</Tabs.Tab>
            <Tabs.Tab value="ideas">Предложения{newIdeas.length > 0 ? ` (${newIdeas.length})` : ""}</Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="board" pt="md">
            <Stack gap="md">
              <Group grow align="flex-start">
                {CHAIN.map((col) => (
                  <Stack key={col} gap="xs">
                    <Badge color={COLUMN[col].color} variant="light" w="fit-content">
                      {COLUMN[col].label} ({posts.filter((p) => p.status === col).length})
                    </Badge>
                    {posts.filter((p) => p.status === col).map((p) => card(p, col))}
                    {posts.every((p) => p.status !== col) && <Text size="sm" c="dimmed">Пусто</Text>}
                  </Stack>
                ))}
              </Group>

              <Card withBorder>
                <Stack gap="sm">
                  <Title order={2} size="h3">Календарь публикаций</Title>
                  <Group>
                    <Button variant="default" onClick={() =>
                      setMonth(({ y, m }) => (m === 0 ? { y: y - 1, m: 11 } : { y, m: m - 1 }))
                    }>‹</Button>
                    <Text fw={500}>{MONTHS[month.m]} {month.y}</Text>
                    <Button variant="default" onClick={() =>
                      setMonth(({ y, m }) => (m === 11 ? { y: y + 1, m: 0 } : { y, m: m + 1 }))
                    }>›</Button>
                  </Group>
                  <Table withTableBorder verticalSpacing="xs" layout="fixed">
                    <Table.Thead>
                      <Table.Tr>
                        {["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"].map((d) => <Table.Th key={d}>{d}</Table.Th>)}
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {Array.from({ length: calendarCells.length / 7 }, (_, row) => (
                        <Table.Tr key={row}>
                          {calendarCells.slice(row * 7, row * 7 + 7).map((day, i) => (
                            <Table.Td key={i} style={{ verticalAlign: "top", minHeight: 60 }}>
                              {day && (
                                <>
                                  <Text size="xs" c="dimmed">{day}</Text>
                                  {(monthPosts.get(day) ?? []).map((p) => (
                                    <Text key={p.id} size="xs" c="blue" span
                                      style={{ cursor: "pointer", display: "block" }}
                                      onClick={() => setSelectedPostId(p.id)}>
                                      {p.title}
                                    </Text>
                                  ))}
                                </>
                              )}
                            </Table.Td>
                          ))}
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                </Stack>
              </Card>

              <Card withBorder component="form" onSubmit={createPost} maw={640}>
                <Stack gap="sm">
                  <Title order={2} size="h3">Новый пост</Title>
                  <TextInput label="Заголовок" value={newTitle} onChange={(e) => setNewTitle(e.currentTarget.value)} required maxLength={200} />
                  <Textarea label="Текст" value={newBody} onChange={(e) => setNewBody(e.currentTarget.value)} required maxLength={10000} minRows={3} />
                  <Button type="submit" loading={busy}>Создать</Button>
                </Stack>
              </Card>
            </Stack>
          </Tabs.Panel>

          <Tabs.Panel value="ideas" pt="md">
            <Stack gap="sm" maw={720}>
              <Title order={2} size="h3">Предложения тем</Title>
              {newIdeas.length === 0 && <Text c="dimmed">Новых идей нет.</Text>}
              {newIdeas.map((i) => (
                <Card key={i.id} withBorder padding="sm">
                  <PostBody text={i.text} />
                  <Group justify="space-between" mt="xs">
                    <Text size="xs" c="dimmed">
                      {userById.get(i.author_id)?.full_name ?? "Пользователь"} ·{" "}
                      {new Date(i.created_at).toLocaleDateString("ru-RU")}
                    </Text>
                    <Group gap="xs">
                      <Button size="xs" onClick={() => actOnIdea(i, "accept")}>Принять</Button>
                      <Button size="xs" variant="outline" color="red" onClick={() => actOnIdea(i, "reject")}>Отклонить</Button>
                    </Group>
                  </Group>
                </Card>
              ))}
            </Stack>
          </Tabs.Panel>
        </Tabs>
      ) : (
        <>
          <Card withBorder component="form" onSubmit={suggestIdea} maw={640}>
            <Stack gap="sm">
              <Title order={2} size="h3">Предложить тему</Title>
              <Textarea
                value={ideaText}
                onChange={(e) => setIdeaText(e.currentTarget.value)}
                placeholder="О чём написать в школьной газете?"
                required maxLength={1000} minRows={2}
              />
              <Button type="submit" loading={busy} w="fit-content">Отправить</Button>
            </Stack>
          </Card>

          <Stack gap="sm" maw={720}>
            <Title order={2} size="h3">Опубликованное</Title>
            {published.length === 0 && <Text c="dimmed">Пока ничего не опубликовано.</Text>}
            {published.map((p) => (
              <Card key={p.id} withBorder padding="md">
                <Group justify="space-between">
                  <Text fw={500}>{p.title}</Text>
                  {p.publish_at && (
                    <Text size="xs" c="dimmed">{new Date(p.publish_at).toLocaleDateString("ru-RU")}</Text>
                  )}
                </Group>
                <PostBody text={p.body} />
              </Card>
            ))}
          </Stack>
        </>
      )}

      <Modal opened={editing !== null} onClose={() => setEditing(null)} title="Редактирование поста">
        <Stack gap="sm">
          <TextInput label="Заголовок" value={editTitle} onChange={(e) => setEditTitle(e.currentTarget.value)} maxLength={200} />
          <Textarea label="Текст" value={editBody} onChange={(e) => setEditBody(e.currentTarget.value)} maxLength={10000} minRows={4} />
          <Select
            label="Ответственный"
            data={assigneeOptions}
            value={editAssignee}
            onChange={(v) => setEditAssignee(v)}
            clearable
            searchable
          />
          <div>
            <Text size="sm" fw={500} mb={4}>Дата публикации</Text>
            <input type="date" value={editPublishAt} onChange={(e) => setEditPublishAt(e.currentTarget.value)} />
          </div>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setEditing(null)}>Отмена</Button>
            <Button onClick={saveEdit} loading={busy}>Сохранить</Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
