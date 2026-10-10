import "@fontsource-variable/inter";
import "@fontsource/outfit/700.css";
import "./styles/app.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { domMax, LazyMotion, MotionConfig } from "motion/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { shouldRetry } from "./api/client";
import { spring } from "./lib/motion";

const queries = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: shouldRetry,
    },
  },
});

// A new build replaces the hashed chunks, so a tab opened before it asks for
// files that are gone. Reload once to get the new index.html; a second failure
// within a minute is a real one and reaches the error page.
window.addEventListener("vite:preloadError", (event) => {
  const key = "openticker:chunk-reload";
  try {
    const last = Number(sessionStorage.getItem(key) ?? 0);
    if (Date.now() - last < 60_000) return;
    sessionStorage.setItem(key, String(Date.now()));
  } catch {
    return;
  }
  event.preventDefault();
  window.location.reload();
});

const root = document.getElementById("root");
if (!root) throw new Error("index.html has no #root");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queries}>
      <LazyMotion features={domMax} strict>
        <MotionConfig reducedMotion="user" transition={spring.snappy}>
          <App />
        </MotionConfig>
      </LazyMotion>
    </QueryClientProvider>
  </StrictMode>,
);
