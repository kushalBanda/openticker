import type { ReactNode } from "react";
import { createBrowserRouter, Outlet, RouterProvider } from "react-router";
import { useSession } from "./api/queries";
import { Building } from "./pages/Building";
import { NotFound } from "./pages/NotFound";
import { Orders } from "./pages/orders/Orders";
import { Positions } from "./pages/positions/Positions";
import { SignIn } from "./pages/SignIn";
import { Strategies } from "./pages/strategies/Strategies";
import { Strategy } from "./pages/strategy/Strategy";
import { Trades } from "./pages/trades/Trades";
import { AppShell } from "./shell/AppShell";
import { PAGES, SETTINGS } from "./shell/nav";

/** Signed in: the app. Not: how to sign in. Unknown yet: the bare ground. */
function Gate() {
  const session = useSession();
  if (session.isPending) return null;
  if (session.data === null) return <SignIn />;
  return <Outlet />;
}

// Pages built so far; the rest say so (ADR 30).
const BUILT: Record<string, ReactNode> = {
  "/positions": <Positions />,
  "/orders": <Orders />,
  "/trades": <Trades />,
  "/strategies": <Strategies />,
};

const router = createBrowserRouter([
  {
    element: <Gate />,
    children: [
      {
        element: <AppShell />,
        children: [
          ...[...PAGES, SETTINGS].map((page) => ({
            path: page.path,
            element: BUILT[page.path] ?? <Building title={page.label} />,
          })),
          { path: "/strategies/:id", element: <Strategy /> },
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
]);

export function App() {
  return <RouterProvider router={router} />;
}
