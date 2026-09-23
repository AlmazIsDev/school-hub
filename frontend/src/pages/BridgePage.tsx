import { useEffect, useState } from "react";
import { Button, Card, Group, Stack, Table, Tabs, Text, TextInput, Title } from "@mantine/core";
import { apiFetch } from "../api";
import { useAuth } from "../auth";

type Report = {
  id: string;
  reporter_id: string;
  reporter_full_name: string;
  reported_user_id: string;
  reported_full_name: string;
  message_id: string | null;
  message_text: string | null;
  reason: string;
  status: "open" | "resolved";
  created_at: string;
};

type Ban = {
  id: string;
  user_id: string;
  full_name: string;
  until: string | null;
  reason: string;
  created_at: string;
};

type Helper = {
  user_id: string;
  full_name: string;
  topics: string[];
  pairs: number;
  avg_score: number | null;
};

type StopWord = { id: string; word: string };

const RESOLVE_ACTIONS = [
  { label: "Отклонить", body: { action: "dismiss" } },
  { label: "Бан 7 дней", body: { action: "ban_days", days: 7 } },
  { label: "Бан 30 дней", body: { action: "ban_days", days: 30 } },
  { label: "Бан навсегда", body: { action: "ban_forever" } },
] as const;

export default function BridgePage() {
  const { user } = useAuth();
  const allowed = user?.role === "teacher" || user?.role === "admin" || user?.role === "superadmin";
  const isAdmin = user?.role === "admin" || user?.role === "superadmin";

  const [reports, setReports] = useState<Report[]>([]);
  const [bans, setBans] = useState<Ban[]>([]);
  const [helpers, setHelpers] = useState<Helper[]>([]);
  const [stopWords, setStopWords] = useState<StopWord[]>([]);
  const [newWord, setNewWord] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setError(null);
    try {
      const [r, b, h] = await Promise.all([
        apiFetch<Report[]>("/bridge/reports?status=open"),
        apiFetch<Ban[]>("/bridge/bans"),
        apiFetch<Helper[]>("/bridge/helpers"),
      ]);
      setReports(r);
      setBans(b);
      setHelpers(h);
      if (isAdmin) setStopWords(await apiFetch<StopWord[]>("/bridge/stop-words"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить данные");
    }
  }

  useEffect(() => {
    if (allowed) refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  function resolve(report: Report, body: { action: string; days?: number }) {
    act(() => apiFetch(`/bridge/reports/${report.id}/resolve`, {
      method: "POST", body: JSON.stringify(body),
    }), "Не удалось разобрать жалобу");
  }

  function removeBan(ban: Ban) {
    act(() => apiFetch(`/bridge/bans/${ban.id}`, { method: "DELETE" }), "Не удалось снять бан");
  }

  function addStopWord(e: React.FormEvent) {
    e.preventDefault();
    const word = newWord.trim();
    if (!word) return;
    act(async () => {
      await apiFetch("/bridge/stop-words", { method: "POST", body: JSON.stringify({ word }) });
      setNewWord("");
    }, "Не удалось добавить стоп-слово");
  }

  function deleteStopWord(w: StopWord) {
    act(() => apiFetch(`/bridge/stop-words/${w.id}`, { method: "DELETE" }), "Не удалось удалить стоп-слово");
  }

  if (!allowed) {
    return <Text c="dimmed">Нет доступа</Text>;
  }

  const activeBans = bans.filter((b) => b.until === null || new Date(b.until) > new Date());

  return (
    <Stack gap="md">
      <Title order={1} size="h2">Помощь</Title>
      {error && <div role="alert">{error}</div>}

      <Tabs defaultValue="reports">
        <Tabs.List>
          <Tabs.Tab value="reports">Жалобы{reports.length > 0 ? ` (${reports.length})` : ""}</Tabs.Tab>
          <Tabs.Tab value="bans">Баны</Tabs.Tab>
          <Tabs.Tab value="helpers">Помощники</Tabs.Tab>
          {isAdmin && <Tabs.Tab value="stop-words">Стоп-слова</Tabs.Tab>}
        </Tabs.List>

        <Tabs.Panel value="reports" pt="md">
          <Table withTableBorder verticalSpacing="xs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Репортер</Table.Th>
                <Table.Th>На кого</Table.Th>
                <Table.Th>Причина</Table.Th>
                <Table.Th>Сообщение</Table.Th>
                <Table.Th>Дата</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {reports.map((r) => (
                <Table.Tr key={r.id}>
                  <Table.Td>{r.reporter_full_name}</Table.Td>
                  <Table.Td>{r.reported_full_name}</Table.Td>
                  <Table.Td>{r.reason}</Table.Td>
                  <Table.Td>{r.message_text ?? "—"}</Table.Td>
                  <Table.Td>{new Date(r.created_at).toLocaleDateString("ru-RU")}</Table.Td>
                  <Table.Td>
                    <Group gap="xs">
                      {RESOLVE_ACTIONS.map((a) => (
                        <Button
                          key={a.label}
                          size="xs"
                          variant={a.label === "Отклонить" ? "outline" : "filled"}
                          color={a.label === "Бан навсегда" ? "red" : undefined}
                          loading={busy}
                          onClick={() => resolve(r, a.body)}
                        >
                          {a.label}
                        </Button>
                      ))}
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
              {reports.length === 0 && (
                <Table.Tr><Table.Td colSpan={6} c="dimmed">Открытых жалоб нет.</Table.Td></Table.Tr>
              )}
            </Table.Tbody>
          </Table>
        </Tabs.Panel>

        <Tabs.Panel value="bans" pt="md">
          <Table withTableBorder verticalSpacing="xs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Кто</Table.Th>
                <Table.Th>До</Table.Th>
                <Table.Th>Причина</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {activeBans.map((b) => (
                <Table.Tr key={b.id}>
                  <Table.Td>{b.full_name}</Table.Td>
                  <Table.Td>{b.until === null ? "навсегда" : new Date(b.until).toLocaleString("ru-RU")}</Table.Td>
                  <Table.Td>{b.reason}</Table.Td>
                  <Table.Td>
                    <Button size="xs" variant="outline" loading={busy} onClick={() => removeBan(b)}>
                      Снять бан
                    </Button>
                  </Table.Td>
                </Table.Tr>
              ))}
              {activeBans.length === 0 && (
                <Table.Tr><Table.Td colSpan={4} c="dimmed">Активных банов нет.</Table.Td></Table.Tr>
              )}
            </Table.Tbody>
          </Table>
        </Tabs.Panel>

        <Tabs.Panel value="helpers" pt="md">
          <Table withTableBorder verticalSpacing="xs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Имя</Table.Th>
                <Table.Th>Темы</Table.Th>
                <Table.Th>Пар</Table.Th>
                <Table.Th>Средняя оценка</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {helpers.map((h) => (
                <Table.Tr key={h.user_id}>
                  <Table.Td>{h.full_name}</Table.Td>
                  <Table.Td>{h.topics.join(", ") || "—"}</Table.Td>
                  <Table.Td>{h.pairs}</Table.Td>
                  <Table.Td>{h.avg_score ?? "—"}</Table.Td>
                </Table.Tr>
              ))}
              {helpers.length === 0 && (
                <Table.Tr><Table.Td colSpan={4} c="dimmed">Пока нет помощников.</Table.Td></Table.Tr>
              )}
            </Table.Tbody>
          </Table>
        </Tabs.Panel>

        {isAdmin && (
          <Tabs.Panel value="stop-words" pt="md">
            <Card withBorder component="form" onSubmit={addStopWord} maw={480}>
              <Group align="flex-end" gap="sm">
                <TextInput
                  flex={1}
                  label="Новое стоп-слово"
                  value={newWord}
                  onChange={(e) => setNewWord(e.currentTarget.value)}
                  maxLength={100}
                  required
                />
                <Button type="submit" loading={busy}>Добавить</Button>
              </Group>
            </Card>
            <Table withTableBorder verticalSpacing="xs" mt="md" maw={480}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Слово</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {stopWords.map((w) => (
                  <Table.Tr key={w.id}>
                    <Table.Td>{w.word}</Table.Td>
                    <Table.Td>
                      <Button size="xs" variant="subtle" color="red" loading={busy} onClick={() => deleteStopWord(w)}>
                        Удалить
                      </Button>
                    </Table.Td>
                  </Table.Tr>
                ))}
                {stopWords.length === 0 && (
                  <Table.Tr><Table.Td colSpan={2} c="dimmed">Стоп-слов нет.</Table.Td></Table.Tr>
                )}
              </Table.Tbody>
            </Table>
          </Tabs.Panel>
        )}
      </Tabs>
    </Stack>
  );
}
