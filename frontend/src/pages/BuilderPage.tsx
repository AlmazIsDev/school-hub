import { useEffect, useState } from "react";
import {
  Badge, Button, Card, Group, NativeSelect, NumberInput, Select, Stack,
  Table, Text, TextInput, Title,
} from "@mantine/core";
import { apiFetch } from "../api";

type BlockType = "question" | "branch" | "hint" | "end";

type Block = {
  id: string;
  type: BlockType;
  text: string;
  options: string[];
  next: string;
  conditionAnswer: string;
  then: string;
  else: string;
  score: number | string;
};

type BlockOut = Record<string, unknown> & { id: string; type: BlockType };

type Quest = {
  id: string;
  title: string;
  class_id: string;
  status: "draft" | "published" | "closed";
  structure: { blocks: BlockOut[] };
};

type SchoolClass = { id: string; grade: number; letter: string };

type Stats = {
  runs: number;
  finished: number;
  avg_score: number | null;
  funnel: { block_id: string; type: BlockType; reached: number }[];
};

const STATUS_BADGE: Record<Quest["status"], { color: string; label: string }> = {
  draft: { color: "gray", label: "Черновик" },
  published: { color: "green", label: "Опубликован" },
  closed: { color: "red", label: "Закрыт" },
};

const TYPE_LABEL: Record<BlockType, string> = {
  question: "Вопрос",
  branch: "Ветвление",
  hint: "Подсказка",
  end: "Финал",
};

const BLOCK_TYPE_OPTIONS = (Object.keys(TYPE_LABEL) as BlockType[]).map((t) => ({ value: t, label: TYPE_LABEL[t] }));

function emptyBlock(id: string): Block {
  return { id, type: "question", text: "", options: ["", ""], next: "", conditionAnswer: "", then: "", else: "", score: 0 };
}

/** id автогенерируем на клиенте: b1, b2... — берём свободный номер */
function nextBlockId(blocks: Block[]): string {
  const used = new Set(blocks.map((b) => b.id));
  for (let i = 1; ; i++) {
    if (!used.has(`b${i}`)) return `b${i}`;
  }
}

function fromServer(b: BlockOut): Block {
  const base = emptyBlock(b.id);
  base.type = b.type;
  if (b.type === "question") {
    Object.assign(base, { text: b.text as string, options: b.options as string[], next: b.next as string });
  } else if (b.type === "branch") {
    const cond = b.condition as { answer: string };
    Object.assign(base, { conditionAnswer: cond.answer, then: b.then as string, else: b["else"] as string });
  } else if (b.type === "hint") {
    Object.assign(base, { text: b.text as string, next: b.next as string });
  } else {
    base.score = b.score as number;
  }
  return base;
}

function toServer(b: Block): BlockOut {
  if (b.type === "question") {
    return { id: b.id, type: b.type, text: b.text, options: b.options, next: b.next };
  }
  if (b.type === "branch") {
    return { id: b.id, type: b.type, condition: { answer: b.conditionAnswer }, then: b.then, else: b.else };
  }
  if (b.type === "hint") {
    return { id: b.id, type: b.type, text: b.text, next: b.next };
  }
  return { id: b.id, type: b.type, score: Number(b.score) };
}

export default function BuilderPage() {
  const [quests, setQuests] = useState<Quest[]>([]);
  const [classes, setClasses] = useState<SchoolClass[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // view: список | редактор (null = новый) | аналитика
  const [editing, setEditing] = useState<Quest | null | undefined>(undefined);
  const [statsQuest, setStatsQuest] = useState<Quest | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);

  // форма редактора
  const [title, setTitle] = useState("");
  const [classId, setClassId] = useState("");
  const [blocks, setBlocks] = useState<Block[]>([emptyBlock("b1")]);

  async function refresh() {
    setError(null);
    try {
      setQuests(await apiFetch<Quest[]>("/builder/quests"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить квесты");
    }
  }

  useEffect(() => {
    refresh();
    apiFetch<SchoolClass[]>("/classes").then(setClasses).catch(() => {});
  }, []);

  async function act(q: Quest, action: "publish" | "close") {
    if (busy) return;
    setBusy(true);
    try {
      await apiFetch(`/builder/quests/${q.id}/${action}`, { method: "POST" });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось изменить статус");
    } finally {
      setBusy(false);
    }
  }

  function openEditor(q: Quest | null) {
    setError(null);
    if (q) {
      setTitle(q.title);
      setClassId(q.class_id);
      setBlocks(q.structure.blocks.map(fromServer));
    } else {
      setTitle("");
      setClassId("");
      setBlocks([emptyBlock("b1")]);
    }
    setEditing(q);
  }

  function setBlock(i: number, patch: Partial<Block>) {
    setBlocks((bs) => bs.map((b, idx) => (idx === i ? { ...b, ...patch } : b)));
  }

  function setOption(i: number, oi: number, value: string) {
    setBlocks((bs) => bs.map((b, idx) => (idx === i ? { ...b, options: b.options.map((o, j) => (j === oi ? value : o)) } : b)));
  }

  function changeType(i: number, type: BlockType) {
    setBlocks((bs) => bs.map((b, idx) => (idx === i ? { ...emptyBlock(b.id), type } : b)));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    // лёгкая клиентская проверка только для UX — остальное скажет валидатор бэка
    if (!title.trim() || !classId || blocks.length === 0) {
      setError("Заполните название и класс, добавьте хотя бы один блок");
      return;
    }
    setBusy(true);
    const body = { title, class_id: classId, structure: { blocks: blocks.map(toServer) } };
    try {
      if (editing) {
        await apiFetch(`/builder/quests/${editing.id}`, { method: "PUT", body: JSON.stringify(body) });
      } else {
        await apiFetch("/builder/quests", { method: "POST", body: JSON.stringify(body) });
      }
      setEditing(undefined);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить квест");
    } finally {
      setBusy(false);
    }
  }

  async function openStats(q: Quest) {
    setError(null);
    setStatsQuest(q);
    setStats(null);
    try {
      setStats(await apiFetch<Stats>(`/builder/quests/${q.id}/stats`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить аналитику");
    }
  }

  const classOptions = classes.map((c) => ({ value: c.id, label: `${c.grade}«${c.letter}»` }));
  const idOptions = blocks.map((b) => ({ value: b.id, label: `${b.id} (${TYPE_LABEL[b.type]})` }));
  const idWithEmpty = [{ value: "", label: "— выберите блок —" }, ...idOptions];

  function renderBlockFields(b: Block, i: number) {
    if (b.type === "question") {
      return (
        <>
          <TextInput label="Текст вопроса" value={b.text} onChange={(e) => setBlock(i, { text: e.currentTarget.value })} maxLength={500} />
          {b.options.map((o, oi) => (
            <Group key={oi} align="flex-end" gap="xs" wrap="nowrap">
              <TextInput flex={1} label={`Вариант ${oi + 1}`} value={o} onChange={(e) => setOption(i, oi, e.currentTarget.value)} maxLength={200} />
              {b.options.length > 2 && (
                <Button variant="subtle" color="red" mb={4} onClick={() => setBlock(i, { options: b.options.filter((_, j) => j !== oi) })}>
                  Убрать
                </Button>
              )}
            </Group>
          ))}
          {b.options.length < 6 && (
            <Button variant="outline" size="xs" onClick={() => setBlock(i, { options: [...b.options, ""] })}>
              Добавить вариант
            </Button>
          )}
          <Select label="Переход (next)" data={idWithEmpty} value={b.next} onChange={(v) => setBlock(i, { next: v ?? "" })} w={280} />
        </>
      );
    }
    if (b.type === "branch") {
      return (
        <>
          <TextInput label="Ответ (условие)" value={b.conditionAnswer} onChange={(e) => setBlock(i, { conditionAnswer: e.currentTarget.value })} maxLength={200} />
          <Group gap="xs">
            <Select label="then (ответ совпал)" data={idWithEmpty} value={b.then} onChange={(v) => setBlock(i, { then: v ?? "" })} w={260} />
            <Select label="else (не совпал)" data={idWithEmpty} value={b.else} onChange={(v) => setBlock(i, { else: v ?? "" })} w={260} />
          </Group>
        </>
      );
    }
    if (b.type === "hint") {
      return (
        <>
          <TextInput label="Текст подсказки" value={b.text} onChange={(e) => setBlock(i, { text: e.currentTarget.value })} maxLength={500} />
          <Select label="Переход (next)" data={idWithEmpty} value={b.next} onChange={(v) => setBlock(i, { next: v ?? "" })} w={280} />
        </>
      );
    }
    return <NumberInput hideControls allowDecimal={false} allowNegative={false} label="Балл (score)" value={b.score} onChange={(v) => setBlock(i, { score: v })} />;
  }

  function renderEditor() {
    return (
      <Card withBorder component="form" onSubmit={submit} maw={720}>
        <Stack gap="sm">
          <Group justify="space-between">
            <Title order={2} size="h3">{editing ? "Редактор квеста" : "Новый квест"}</Title>
            <Button variant="subtle" onClick={() => setEditing(undefined)}>К списку</Button>
          </Group>
          <TextInput label="Название" value={title} onChange={(e) => setTitle(e.currentTarget.value)} required maxLength={200} />
          <NativeSelect
            label="Класс"
            data={[{ value: "", label: "Выберите класс" }, ...classOptions]}
            value={classId}
            onChange={(e) => setClassId(e.currentTarget.value)}
            required
          />
          <Text size="sm" c="dimmed">Первый блок — стартовый, прохождение начинается с него.</Text>
          {blocks.map((b, i) => (
            <Card key={b.id} withBorder padding="sm" radius="sm">
              <Stack gap="xs">
                <Group justify="space-between">
                  <Group gap="xs">
                    <Text fw={500}>{b.id}</Text>
                    <Select
                      data={BLOCK_TYPE_OPTIONS}
                      value={b.type}
                      onChange={(v) => changeType(i, (v ?? "question") as BlockType)}
                      w={160}
                      aria-label={`Тип блока ${b.id}`}
                    />
                  </Group>
                  <Button
                    variant="subtle" color="red" size="xs"
                    disabled={blocks.length === 1}
                    onClick={() => setBlocks((bs) => bs.filter((_, idx) => idx !== i))}
                  >
                    Удалить блок
                  </Button>
                </Group>
                {renderBlockFields(b, i)}
              </Stack>
            </Card>
          ))}
          <Button variant="outline" onClick={() => setBlocks((bs) => [...bs, emptyBlock(nextBlockId(bs))])} w={200}>
            Добавить блок
          </Button>
          <Button type="submit" loading={busy}>Сохранить</Button>
        </Stack>
      </Card>
    );
  }

  function renderStats() {
    if (!statsQuest) return null;
    const started = stats?.runs ?? 0;
    return (
      <Stack gap="md">
        <Group>
          <Button variant="subtle" onClick={() => setStatsQuest(null)}>К списку</Button>
          <Title order={2} size="h3">Аналитика: {statsQuest.title}</Title>
        </Group>
        {error && <div role="alert">{error}</div>}
        {stats && (
          <>
            <Group gap="lg">
              <Text>Запусков: <b>{stats.runs}</b></Text>
              <Text>Дошли до конца: <b>{stats.finished}</b></Text>
              <Text>Бросили на середине: <b>{stats.runs - stats.finished}</b></Text>
              <Text>Средний балл: <b>{stats.avg_score ?? "—"}</b></Text>
            </Group>
            <Table withTableBorder verticalSpacing="xs" maw={560}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Блок</Table.Th>
                  <Table.Th>Тип</Table.Th>
                  <Table.Th>Дошло</Table.Th>
                  <Table.Th>% от стартовавших</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {stats.funnel.map((f) => (
                  <Table.Tr key={f.block_id}>
                    <Table.Td>{f.block_id}</Table.Td>
                    <Table.Td>{TYPE_LABEL[f.type]}</Table.Td>
                    <Table.Td>{f.reached}</Table.Td>
                    <Table.Td>{started > 0 ? Math.round((f.reached / started) * 100) : 0}%</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </>
        )}
      </Stack>
    );
  }

  if (editing !== undefined) {
    return (
      <Stack gap="md">
        <Title order={1} size="h2">Квесты</Title>
        {error && <div role="alert">{error}</div>}
        {renderEditor()}
      </Stack>
    );
  }

  if (statsQuest) return renderStats();

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={1} size="h2">Квесты</Title>
        <Button onClick={() => openEditor(null)}>Новый квест</Button>
      </Group>
      {error && <div role="alert">{error}</div>}
      <Table withTableBorder verticalSpacing="xs">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Название</Table.Th>
            <Table.Th>Класс</Table.Th>
            <Table.Th>Статус</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {quests.map((q) => (
            <Table.Tr key={q.id}>
              <Table.Td>{q.title}</Table.Td>
              <Table.Td>{classOptions.find((c) => c.value === q.class_id)?.label ?? q.class_id}</Table.Td>
              <Table.Td><Badge color={STATUS_BADGE[q.status].color}>{STATUS_BADGE[q.status].label}</Badge></Table.Td>
              <Table.Td>
                <Group gap="xs">
                  {q.status === "draft" && <Button size="xs" onClick={() => act(q, "publish")}>Опубликовать</Button>}
                  {q.status === "published" && <Button size="xs" variant="outline" color="red" onClick={() => act(q, "close")}>Закрыть</Button>}
                  {q.status === "draft" && <Button size="xs" variant="light" onClick={() => openEditor(q)}>Редактор</Button>}
                  {q.status !== "draft" && <Button size="xs" variant="light" onClick={() => openStats(q)}>Аналитика</Button>}
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
          {quests.length === 0 && (
            <Table.Tr><Table.Td colSpan={4} c="dimmed">Квестов пока нет.</Table.Td></Table.Tr>
          )}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}
