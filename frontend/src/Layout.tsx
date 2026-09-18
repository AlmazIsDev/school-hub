import { AppShell, Burger, Button, Group, NavLink, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "./auth";

export default function Layout() {
  const [opened, { toggle }] = useDisclosure(false);
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const canModerate = user?.role === "teacher" || user?.role === "admin";

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
        {canModerate && (
          <NavLink
            label="Помощь"
            active={location.pathname === "/bridge"}
            onClick={() => { navigate("/bridge"); toggle(); }}
          />
        )}
      </AppShell.Navbar>
      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
