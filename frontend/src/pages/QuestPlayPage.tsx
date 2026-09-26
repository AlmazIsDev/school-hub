import { useEffect, useState } from "react";
import { Alert, Badge, Button, Card, Center, Loader, Group, Stack, Text, Title } from "@mantine/core";
import { apiFetch } from "../api";

type QuestListItem = { id: string; title: string };

type PlayBlock = {
  id: string;
  type: "question" | "hint";
  text: string;
  options?: string[];
};

type PlayState = {
  run_id: string;
  finished: boolean;
  score: number | null;
  block: PlayBlock | null;
};

export default function QuestPlayPage() {
  const [quests, setQuests] = useState<QuestListItem[]>([]);
  const [state, setState] = useState<PlayState | null>(null);
  const [questId, setQuestId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    apiFetch<QuestListItem[]>("/builder/quests/published")
      .then((qs) => { setQuests(qs); setLoaded(true); })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Не удалось загрузить квесты");
        setLoaded(true);
      });
  }, []);

  async function run(fn: () => Promise<PlayState>) {
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      setState(await fn());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  const start = (q: QuestListItem) =>
    run(async () => {
      setQuestId(q.id);
      return apiFetch<PlayState>(`/builder/quests/${q.id}/play/start`, { method: "POST" });
    });

  const answer = (blockId: string, value: string | null) =>
    run(async () => apiFetch<PlayState>(`/builder/quests/${questId}/play/answer`, {
      method: "POST",
      body: JSON.stringify({ run_id: state!.run_id, block_id: blockId, value }),
    }));

  const stop = () => { setState(null); setQuestId(null); };

  return (
    <Stack gap="md">
      <Title order={1} size="h2">Квесты</Title>
      {error && <Alert color="red" role="alert" withCloseButton onClose={() => setError(null)}>{error}</Alert>}

      {state === null && (
        <Stack gap="sm" maw={560}>
          {!loaded && <Center><Loader /></Center>}
          {quests.length === 0 && <Text c="dimmed">Доступных квестов пока нет.</Text>}
          {quests.map((q) => (
            <Card key={q.id} withBorder padding="sm">
              <Group justify="space-between">
                <Text fw={500}>{q.title}</Text>
                <Button size="xs" onClick={() => start(q)}>Начать</Button>
              </Group>
            </Card>
          ))}
        </Stack>
      )}

      {state !== null && (
        <Card withBorder maw={560}>
          {state.finished ? (
            <Stack gap="sm">
              <Title order={2} size="h3">Квест завершён</Title>
              {state.score !== null && <Text size="lg">Ваш балл: <b>{state.score}</b></Text>}
              <Button variant="light" onClick={stop} w="fit-content">К списку квестов</Button>
            </Stack>
          ) : state.block?.type === "question" ? (
            <Stack gap="sm">
              <Text fw={500}>{state.block.text}</Text>
              <Group gap="xs">
                {state.block.options?.map((o) => (
                  <Button key={o} variant="light" loading={busy}
                    onClick={() => answer(state.block!.id, o)}>{o}</Button>
                ))}
              </Group>
              <Button variant="subtle" color="gray" onClick={stop} w="fit-content">Прервать</Button>
            </Stack>
          ) : state.block?.type === "hint" ? (
            <Stack gap="sm">
              <Text>{state.block.text}</Text>
              <Button loading={busy} onClick={() => answer(state.block!.id, null)} w="fit-content">
                Дальше
              </Button>
            </Stack>
          ) : (
            <Badge color="red">Неизвестный блок</Badge>
          )}
        </Card>
      )}
    </Stack>
  );
}
