import { AppShell, Container, Group, Text } from "@mantine/core";
import { Outlet } from "react-router-dom";
import { Nav } from "./Nav";

export function Layout() {
  return (
    <AppShell header={{ height: 56 }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" gap="xl" wrap="nowrap">
          <Text fw={700}>Normalization Engine</Text>
          <Nav />
        </Group>
      </AppShell.Header>
      <AppShell.Main>
        <Container size="lg" px={0}>
          <Outlet />
        </Container>
      </AppShell.Main>
    </AppShell>
  );
}
