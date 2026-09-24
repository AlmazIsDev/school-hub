import { useState } from "react";
import { Button, Card, Center, PasswordInput, Stack, TextInput, Title } from "@mantine/core";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [schoolCode, setSchoolCode] = useState("");
  const [loginName, setLoginName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(schoolCode, loginName, password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка входа");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Center mih="100vh">
      <Card withBorder w={360} p="lg" component="form" onSubmit={onSubmit}>
        <Stack gap="sm">
          <Title order={1} size="h2">Школьный хаб</Title>
          <TextInput
            label="Код школы"
            placeholder="Например, school1"
            value={schoolCode}
            onChange={(e) => setSchoolCode(e.currentTarget.value)}
            required
          />
          <TextInput
            label="Логин"
            value={loginName}
            onChange={(e) => setLoginName(e.currentTarget.value)}
            required
            autoFocus
          />
          <PasswordInput
            label="Пароль"
            value={password}
            onChange={(e) => setPassword(e.currentTarget.value)}
            required
          />
          {error && <div role="alert">{error}</div>}
          <Button type="submit" loading={busy}>Войти</Button>
        </Stack>
      </Card>
    </Center>
  );
}
