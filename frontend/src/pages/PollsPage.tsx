import { useEffect, useState } from "react";
import { Badge, Button, Card, Group, NativeSelect, Select, Stack, Table, Text, TextInput, Title } from "@mantine/core";
import { apiFetch } from "../api";
import { useAuth } from "../auth";

type QuestionType = "scale1_5" | "free_text";

type Question = { text: string; type: QuestionType };

type Poll = {
  id: string;
  title: string;
  topic: string;
  status: "draft" | "active" | "closed";
  class_id: string;
  created_at: string;
};

type SchoolClass = { id: string; grade: number; letter: string };

const STATUS_BADGE: Record<Poll["status"], { color: string; label: string }> = {
  draft: { color: "gray", label: "Черновик" },
  active: { color: "green", label: "Активен" },
  closed: { color: "red", label: "Закрыт" },
};

const TYPE_OPTIONS = [
  { value: "scale1_5", label: "Шкала 1–5" },
  { value: "free_text", label: "Свободный ответ" },
];

function emptyQuestion(): Question {
  return { text: "", type: "scale1_5" };
}

export default function PollsPage() {
  const { user } = useAuth();
  const canManage = user?.role === "teacher" || user?.role === "admin";

  const [polls, setPolls] = useState<Poll[]>([]);
  const [classes, setClasses] = useState<SchoolClass[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // форма создания
  const [title, setTitle] = useState("");
  const [topic, setTopic] = useState("");
  const [classId, setClassId] = useState("");
  const [questions, setQuestions] = useState<Question[]>([emptyQuestion()]);

  async function refresh() {
    try {
      setPolls(await apiFetch<Poll[]>("/pulse/polls"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить опросы");
    }
  }

  useEffect(() => {
    refresh();
    apiFetch<SchoolClass[]>("/classes").then(setClasses).catch(() => {});
  }, []);

  function setQuestion(i: number, patch: Partial<Question>) {
    setQuestions((qs) => qs.map((q, idx) => (idx === i ? { ...q, ...patch } : q)));
  }

  async function createPoll(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const filled = questions.filter((q) => q.text.trim());
    if (filled.length === 0) {
      setError("Заполните хотя бы один вопрос");
      return;
    }
    setBusy(true);
    try {
      await apiFetch("/pulse/polls", {
        method: "POST",
        body: JSON.stringify({
          title,
          topic,
          class_id: classId,
          questions: filled,
        }),
      });
      setTitle("");
      setTopic("");
      setQuestions([emptyQuestion()]);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось создать опрос");
    } finally {
      setBusy(false);
    }
  }

  async function act(poll: Poll, action: "publish" | "close") {
    setError(null);
    try {
      await apiFetch(`/pulse/polls/${poll.id}/${action}`, { method: "POST" });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось изменить статус");
    }
  }

  const classOptions = classes.map((c) => ({ value: c.id, label: `${c.grade}«${c.letter}»` }));

  return (
    <Stack gap="md">
      <Title order={1} size="h2">Опросы</Title>
      {error && <div role="alert">{error}</div>}

      {!canManage && (
        <Card withBorder>
          <Stack gap="sm">
            <Title order={2} size="h3">Активные опросы</Title>
            {polls.length === 0 && <Text c="dimmed">Пока нет активных опросов.</Text>}
            {polls.map((p) => (
              <Group key={p.id} justify="space-between">
                <div>
                  <Text fw={500}>{p.title}</Text>
                  <Text size="sm" c="dimmed">{p.topic}</Text>
                </div>
                <Text size="sm" c="dimmed">Ответить в боте</Text>
              </Group>
            ))}
          </Stack>
        </Card>
      )}

      {canManage && (
        <Table withTableBorder highlightOnHover verticalSpacing="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Название</Table.Th>
              <Table.Th>Тема</Table.Th>
              <Table.Th>Статус</Table.Th>
              <Table.Th>Создан</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {polls.map((p) => (
              <Table.Tr key={p.id}>
                <Table.Td>{p.title}</Table.Td>
                <Table.Td>{p.topic}</Table.Td>
                <Table.Td><Badge color={STATUS_BADGE[p.status].color}>{STATUS_BADGE[p.status].label}</Badge></Table.Td>
                <Table.Td>{new Date(p.created_at).toLocaleDateString("ru-RU")}</Table.Td>
                <Table.Td>
                  <Group gap="xs">
                    {p.status === "draft" && <Button size="xs" onClick={() => act(p, "publish")}>Опубликовать</Button>}
                    {p.status === "active" && <Button size="xs" variant="outline" color="red" onClick={() => act(p, "close")}>Закрыть</Button>}
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
            {polls.length === 0 && (
              <Table.Tr><Table.Td colSpan={5} c="dimmed">Опросов пока нет.</Table.Td></Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      )}

      {canManage && (
        <Card withBorder component="form" onSubmit={createPoll} maw={640}>
          <Stack gap="sm">
            <Title order={2} size="h3">Новый опрос</Title>
            <TextInput label="Название" value={title} onChange={(e) => setTitle(e.currentTarget.value)} required maxLength={200} />
            <TextInput label="Тема" value={topic} onChange={(e) => setTopic(e.currentTarget.value)} required maxLength={100} />
            <NativeSelect
              label="Класс"
              data={[{ value: "", label: "Выберите класс" }, ...classOptions]}
              value={classId}
              onChange={(e) => setClassId(e.currentTarget.value)}
              required
            />
            {questions.map((q, i) => (
              <Group key={i} align="flex-end" gap="xs" wrap="nowrap">
                <TextInput
                  flex={1}
                  label={`Вопрос ${i + 1}`}
                  value={q.text}
                  onChange={(e) => setQuestion(i, { text: e.currentTarget.value })}
                  required
                  maxLength={500}
                />
                <Select
                  w={190}
                  label="Тип"
                  data={TYPE_OPTIONS}
                  value={q.type}
                  onChange={(v) => setQuestion(i, { type: (v ?? "scale1_5") as QuestionType })}
                />
                {questions.length > 1 && (
                  <Button variant="subtle" color="red" onClick={() => setQuestions((qs) => qs.filter((_, idx) => idx !== i))}>
                    Удалить
                  </Button>
                )}
              </Group>
            ))}
            {questions.length < 5 && (
              <Button variant="outline" onClick={() => setQuestions((qs) => [...qs, emptyQuestion()])}>
                Добавить вопрос
              </Button>
            )}
            <Button type="submit" loading={busy}>Создать опрос</Button>
          </Stack>
        </Card>
      )}
    </Stack>
  );
}
