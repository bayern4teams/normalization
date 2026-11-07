import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";
import { router } from "./app/routes";

const queryClient = new QueryClient();

// Light theme only, no colour-scheme switch (R10). Mantine's default font stack is system fonts.
export default function App() {
  return (
    <MantineProvider forceColorScheme="light">
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </MantineProvider>
  );
}
