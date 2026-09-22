import { AppShell, Burger, Button, Container, Group, NavLink, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "./auth";

export default function Layout() {
  const [opened, { toggle }] = useDisclosure(false);
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const canModerate = user?.role === "teacher" || user?.role === "admin";
  const isAdmin = user?.role === "admin";
  const isSuperadmin = user?.role === "superadmin";

  return (
    <AppShell header={{ height: 56 }} navbar={{ width: 220, breakpoint: "sm", collapsed: { mobile: !opened } }}>
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group>
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Меню" />
            <Title order={1} size="h3">Школьный хаб</Title>
          </Group>
          <Group>
            <span>{user?.role}</span>
            <Button variant="subtle" onClick={() => { logout(); navigate("/login"); }}>Выйти</Button>
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
      <AppShell.Main bg="gray.0">
        <Container size="lg" px="md" py="lg">
          <Outlet />
        </Container>
      </AppShell.Main>
    </AppShell>
  );
}
