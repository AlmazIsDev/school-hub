import { useState } from "react";
import { Button, Card, PasswordInput, Stack, Text, Title } from "@mantine/core";
import { apiFetch } from "../api";
import { useAuth } from "../auth";

export default function Profile() {
  const { user, mustChangePassword, passwordChanged } = useAuth();
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [vkCode, setVkCode] = useState<string | null>(null);
  const [vkLinked, setVkLinked] = useState(false);
  const [busy, setBusy] = useState(false);

  async function changePassword(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setMsg(null);
    if (password !== password2) {
      setError("Пароли не совпадают");
      return;
    }
    setBusy(true);
    try {
      await apiFetch("/auth/first-password", {
        method: "POST",
        body: JSON.stringify({ new_password: password }),
      });
      passwordChanged();
      setMsg("Пароль изменён");
      setPassword("");
      setPassword2("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сменить пароль");
    } finally {
      setBusy(false);
    }
  }

  async function getVkCode() {
    setError(null);
    try {
      const res = await apiFetch<{ code: string }>("/me/vk-code", { method: "POST" });
      setVkCode(res.code);
      setVkLinked(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось получить код");
    }
  }

  async function unlinkVk() {
    setError(null);
    try {
      await apiFetch("/me/vk", { method: "DELETE" });
      setVkCode(null);
      setVkLinked(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось отвязать VK");
    }
  }

  return (
    <Stack gap="md" maw={480}>
      <Title order={1} size="h2">Профиль</Title>
      {mustChangePassword && (
        <div role="alert">Смените временный пароль перед началом работы.</div>
      )}
      {error && <div role="alert">{error}</div>}
      {msg && <div>{msg}</div>}

      <Card withBorder component="form" onSubmit={changePassword}>
        <Stack gap="sm">
          <Title order={2} size="h3">Смена пароля</Title>
          <PasswordInput
            label="Новый пароль"
            value={password}
            onChange={(e) => setPassword(e.currentTarget.value)}
            required
          />
          <PasswordInput
            label="Повторите пароль"
            value={password2}
            onChange={(e) => setPassword2(e.currentTarget.value)}
            required
          />
          <Button type="submit" loading={busy}>Сменить пароль</Button>
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="sm">
          <Title order={2} size="h3">Привязка VK</Title>
          {vkCode ? (
            <Text>Ваш код: <Text span fw={700} style={{ userSelect: "all" }}>{vkCode}</Text>. Отправьте его боту.</Text>
          ) : (
            <Text c="dimmed">{vkLinked ? "Код отправлен боту." : "VK не привязан."}</Text>
          )}
          <Button onClick={getVkCode}>{vkLinked ? "Получить новый код" : "Получить код VK"}</Button>
          {vkLinked && <Button variant="outline" color="red" onClick={unlinkVk}>Отвязать</Button>}
        </Stack>
      </Card>
      {user && <Text size="sm" c="dimmed">Роль: {user.role}</Text>}
    </Stack>
  );
}
