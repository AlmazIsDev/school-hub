import { useEffect, useState } from "react";
import { Button, Card, Group, Stack, Table, Text, Title, Badge, Paper } from "@mantine/core";
import { useParams } from "react-router-dom";
import { apiBlob, apiFetch } from "../api";

type QuestionType = "scale1_5" | "free_text";

type ResultQuestion = {
  text: string;
  type: QuestionType;
  answers: Record<string, number> | string[];
};

type Results = {
  poll: { title: string; topic: string; status: string };
  started: number;
  completed: number;
  questions: ResultQuestion[];
};

function ScaleBars({ counts }: { counts: Record<string, number> }) {
  const total = Object.values(counts).reduce((s, n) => s + n, 0);
  if (total === 0) return <Text c="dimmed" size="sm">Нет ответов</Text>;
  return (
    <Stack gap={4}>
      {Object.entries(counts).map(([value, n]) => (
        <Group key={value} gap="sm" wrap="nowrap">
          <Text size="sm" w={16} ta="right">{value}</Text>
          <Paper flex={1} h={18} bg="gray.1" style={{ overflow: "hidden" }}>
            {/* CSS-бар вместо @mantine/charts - ради гистограммы тянуть зависимость не стали */}
            <div style={{ width: `${(n / total) * 100}%`, height: "100%", background: "var(--mantine-color-blue-6)" }} />
          </Paper>
          <Text size="sm" w={30} ta="right">{n}</Text>
        </Group>
      ))}
    </Stack>
  );
}

export default function PollResultsPage() {
  const { id } = useParams();
  const [results, setResults] = useState<Results | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<Results>(`/pulse/polls/${id}/results`).then(setResults).catch(
      (err) => setError(err instanceof Error ? err.message : "Не удалось загрузить результаты"),
    );
  }, [id]);

  if (error) return <div role="alert">{error}</div>;
  if (!results) return <Text>Загрузка...</Text>;

  async function downloadCsv() {
    const blob = await apiBlob(`/pulse/polls/${id}/results.csv`);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `poll-${id}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={1} size="h2">{results.poll.title}</Title>
        <Group>
          <Badge color="gray">{results.poll.topic}</Badge>
          <Button variant="light" onClick={downloadCsv}>Скачать CSV</Button>
        </Group>
      </Group>
      <Text c="dimmed">
        Начали: {results.started} · Прошли полностью: {results.completed}
      </Text>

      {results.questions.map((q, i) => (
        <Card key={i} withBorder>
          <Stack gap="sm">
            <Title order={3} size="h4">{i + 1}. {q.text}</Title>
            {q.type === "scale1_5"
              ? <ScaleBars counts={q.answers as Record<string, number>} />
              : (
                (q.answers as string[]).length === 0
                  ? <Text c="dimmed" size="sm">Нет ответов</Text>
                  : (
                    <Table withTableBorder verticalSpacing="xs">
                      <Table.Tbody>
                        {(q.answers as string[]).map((t, j) => (
                          <Table.Tr key={j}><Table.Td>{t}</Table.Td></Table.Tr>
                        ))}
                      </Table.Tbody>
                    </Table>
                  )
              )}
          </Stack>
        </Card>
      ))}
    </Stack>
  );
}
