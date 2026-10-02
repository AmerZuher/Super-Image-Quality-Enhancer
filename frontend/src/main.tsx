import "./styles/globals.css";
import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { router } from "./app/router";
import { ApiError } from "./lib/api/client";
import { keys } from "./lib/api/keys";
import { connectEvents } from "./lib/events";
import { applyTheme, useUi } from "./lib/ui-store";

const queryClient: QueryClient = new QueryClient({
  queryCache: new QueryCache({
    // A revoked key or an expired sign-in: re-check, which swaps the app for the sign-in screen.
    onError: (error) => {
      const code = error instanceof ApiError ? error.problem.code : undefined;
      if (code === "auth.required" || code === "auth.invalid_key") {
        void queryClient.invalidateQueries({ queryKey: keys.auth });
      }
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      refetchOnWindowFocus: true,
      // Don't hammer the API with retries for errors it explained (4xx problem+json).
      retry: (count, error) =>
        !(error instanceof ApiError && (error.problem.status ?? 500) < 500) && count < 2,
    },
  },
});

function App() {
  useEffect(() => connectEvents(queryClient), []);
  useEffect(() => applyTheme(useUi.getState().theme), []);
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}

const root = document.getElementById("root");
if (!root) throw new Error("#root element missing from index.html");
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
