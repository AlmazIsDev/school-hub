import { useEffect, useState } from "react";
import { ActionIcon, AppShell, Burger, Button, Container, Group, NavLink, Select, Title, useMantineColorScheme } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "./auth";
import { apiFetch, getActiveSchool, getImpersonator, setActiveSchool, stopImpersonation } from "./api";

type School = { id: string; name: string; code: string };

/** Селектор активной школы для платформенного админа: все API идут в её контексте. */
function SchoolPicker() {
  const [schools, setSchools] = useState<School[]>([]);
  useEffect(() => {
    apiFetch<School[]>("/schools").then(setSchools).catch(() => {});
  }, []);
  if (schools.length === 0) return null;
  return (
    <Select
      placeholder="Школа не выбрана"
      data={schools.map((s) => ({ value: s.id, label: `${s.name} (${s.code})` }))}
      value={getActiveSchool()}
      onChange={(v) => { setActiveSchool(v); window.location.reload(); }}
      w={240}
      clearable
      aria-label="Школа"
    />
  );
}

export default function Layout() {
  const [opened, { toggle }] = useDisclosure(false);
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { colorScheme, toggleColorScheme } = useMantineColorScheme();
  const [impersonator, setImpersonator] = useState(getImpersonator);
  const canModerate = user?.role === "teacher" || user?.role === "admin" || user?.role === "superadmin";
  const isAdmin = user?.role === "admin" || user?.role === "superadmin";
  const isSuperadmin = user?.role === "superadmin";

  const exitImpersonation = () => {
    stopImpersonation();
    setImpersonator(null);
    window.location.href = "/admin";
  };

  return (
    <AppShell header={{ height: 56 }} navbar={{ width: 220, breakpoint: "sm", collapsed: { mobile: !opened } }}>
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group>
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Меню" />
            <Title order={1} size="h3">Школьный хаб</Title>
          </Group>
          <Group>
            {isSuperadmin && <SchoolPicker />}
            <span>{user?.role}</span>
            <ActionIcon
              variant="default" size="lg" aria-label="Сменить тему"
              onClick={() => toggleColorScheme()}
            >
              {colorScheme === "dark" ? "☀" : "☾"}
            </ActionIcon>
            {impersonator ? (
              <Button variant="light" color="orange" onClick={exitImpersonation}>
                Вернуться на {impersonator.name}
              </Button>
            ) : (
              <Button variant="subtle" onClick={() => { logout(); navigate("/login"); }}>Выйти</Button>
            )}
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="xs">
        <NavLink
          label="Профиль"
          active={location.pathname === "/profile"}
          onClick={() => { navigate("/profile"); toggle(); }}
        />
        <NavLink
          label="Опросы"
          active={location.pathname === "/polls"}
          onClick={() => { navigate("/polls"); toggle(); }}
        />
        <NavLink
          label="Дежурства"
          active={location.pathname === "/duty"}
          onClick={() => { navigate("/duty"); toggle(); }}
        />
        <NavLink
          label="Квесты"
          active={location.pathname === "/quests"}
          onClick={() => { navigate("/quests"); toggle(); }}
        />
        <NavLink
          label="Медиацентр"
          active={location.pathname === "/media"}
          onClick={() => { navigate("/media"); toggle(); }}
        />
        <NavLink
          label="Карта"
          active={location.pathname === "/navigator"}
          onClick={() => { navigate("/navigator"); toggle(); }}
        />
        {canModerate && (
          <NavLink
            label="Помощь"
            active={location.pathname === "/bridge"}
            onClick={() => { navigate("/bridge"); toggle(); }}
          />
        )}
        {canModerate && (
          <NavLink
            label="Конструктор квестов"
            active={location.pathname === "/builder"}
            onClick={() => { navigate("/builder"); toggle(); }}
          />
        )}
        {isAdmin && (
          <NavLink
            label="Администрирование"
            active={location.pathname === "/admin"}
            onClick={() => { navigate("/admin"); toggle(); }}
          />
        )}
        {isSuperadmin && (
          <NavLink
            label="Школы"
            active={location.pathname === "/schools"}
            onClick={() => { navigate("/schools"); toggle(); }}
          />
        )}
      </AppShell.Navbar>
      {/* AppShell.Main не трогаем: у него встроенный padding-top под хедер */}
      <AppShell.Main bg="var(--mantine-color-body)">
        <Container size="xl" px="md" py="lg">
          <Outlet />
        </Container>
      </AppShell.Main>
    </AppShell>
  );
}
