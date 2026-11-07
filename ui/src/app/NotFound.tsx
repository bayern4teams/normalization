import { Button, Stack, Text, Title } from "@mantine/core";
import { Link } from "react-router-dom";

export function NotFound() {
  return (
    <Stack align="flex-start">
      <Title order={2}>Page not found</Title>
      <Text>This address is not one of the five screens.</Text>
      <Button component={Link} to="/connections">
        Go to Connections
      </Button>
    </Stack>
  );
}
