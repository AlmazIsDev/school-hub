import { useEffect, useState } from "react";
import { Badge, Button, Card, Group, NativeSelect, Select, Stack, Table, Text, TextInput, Title } from "@mantine/core";
import { Link } from "react-router-dom";
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

type WeakTopic = { poll_id: string; title: string; topic: string; avg: number; n_answers: number };

type CompareResult = {
  a: { title: string; avgs: (number | null)[] };
  b: { title: string; avgs: (number | null)[] };
};

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

  // аналитика
  const [weak, setWeak] = useState<WeakTopic[]>([]);
  const [compareA, setCompareA] = useState("");
  const [compareB, setCompareB] = useState("");
  const [compareResult, setCompareResult] = useState<CompareResult | null>(null);

  async function refresh() {
    setError(null);
    try {
      setPolls(await apiFetch<Poll[]>("/pulse/polls"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить опросы");
    }
  }

  useEffect(() => {
    refresh();
    apiFetch<SchoolClass[]>("/classes").then(setClasses).catch(() => {});
    if (canManage) apiFetch<WeakTopic[]>("/pulse/topics").then(setWeak).catch(() => {});
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
      setClassId("");
      setQuestions([emptyQuestion()]);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось создать опрос");
    } finally {
      setBusy(false);
    }
  }

  async function act(poll: Poll, action: "publish" | "close") {
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      await apiFetch(`/pulse/polls/${poll.id}/${action}`, { method: "POST" });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось изменить статус");
    } finally {
      setBusy(false);
    }
  }

  const classOptions = classes.map((c) => ({ value: c.id, label: `${c.grade}«${c.letter}»` }));

  const closedPolls = polls.filter((p) => p.status === "closed");
  const closedByTopic = new Map<string, Poll[]>();
  for (const p of closedPolls) {
    closedByTopic.set(p.topic, [...(closedByTopic.get(p.topic) ?? []), p]);
  }

  // В списке B — только опросы той же темы, что выбрана в A
  function sameAsA(topics: [string, Poll[]][], pollA: string) {
    const topic = topics.flatMap(([t, ps]) => (ps.some((p) => p.id === pollA) ? [t] : []))[0];
    return (topics.find(([t]) => t === topic)?.[1] ?? [])
      .filter((p) => p.id !== pollA)
      .map((p) => ({ value: p.id, label: `${topic} — ${p.title}` }));
  }

  async function runCompare() {
    setError(null);
    setCompareResult(null);
    try {
      setCompareResult(await apiFetch<CompareResult>(
        `/pulse/compare?a=${compareA}&b=${compareB}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сравнить");
    }
  }

  // Пары для сравнения: только закрытые опросы с одинаковой темой
  const comparableTopics = [...closedByTopic.entries()].filter(([, ps]) => ps.length >= 2);

  function renderCompareTable() {
    if (!compareResult) return null;
    return (
      <Table withTableBorder verticalSpacing="xs" maw={480}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Шкальный вопрос</Table.Th>
            <Table.Th>{compareResult.a.title}</Table.Th>
            <Table.Th>{compareResult.b.title}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {Array.from({ length: Math.max(compareResult.a.avgs.length, compareResult.b.avgs.length) }, (_, i) => (
            <Table.Tr key={i}>
              <Table.Td>Вопрос {i + 1}</Table.Td>
              <Table.Td>{compareResult.a.avgs[i] ?? "—"}</Table.Td>
              <Table.Td>{compareResult!.b.avgs[i] ?? "—"}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    );
  }

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
                    {p.status !== "draft" && (
                      <Button size="xs" variant="light" component={Link} to={`/polls/${p.id}/results`}>Результаты</Button>
                    )}
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

      {canManage && weak.length > 0 && (
        <Card withBorder>
          <Stack gap="sm">
            <Title order={2} size="h3">Просевшие темы (средняя ниже 3.5)</Title>
            <Table withTableBorder verticalSpacing="xs">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Опрос</Table.Th>
                  <Table.Th>Тема</Table.Th>
                  <Table.Th>Средняя</Table.Th>
                  <Table.Th>Ответов</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {weak.map((w) => (
                  <Table.Tr key={w.poll_id}>
                    <Table.Td>{w.title}</Table.Td>
                    <Table.Td>{w.topic}</Table.Td>
                    <Table.Td><Text c="red" span>{w.avg}</Text></Table.Td>
                    <Table.Td>{w.n_answers}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Stack>
        </Card>
      )}

      {canManage && comparableTopics.length > 0 && (
        <Card withBorder>
          <Stack gap="sm">
            <Title order={2} size="h3">Сравнение опросов</Title>
            <Group align="flex-end" gap="sm">
              <Select
                label="Опрос A"
                data={comparableTopics.flatMap(([topic, ps]) => ps.map((p) => ({ value: p.id, label: `${topic} — ${p.title}` })))}
                value={compareA}
                onChange={(v) => { setCompareA(v ?? ""); setCompareB(""); setCompareResult(null); }}
                w={320}
              />
              <Select
                label="Опрос B"
                data={sameAsA(comparableTopics, compareA)}
                value={compareB}
                onChange={(v) => setCompareB(v ?? "")}
                w={320}
              />
              <Button disabled={!compareA || !compareB} onClick={runCompare}>Сравнить</Button>
            </Group>
            {renderCompareTable()}
          </Stack>
        </Card>
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
