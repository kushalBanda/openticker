import type { ReactNode } from "react";
import { createBrowserRouter, Outlet, RouterProvider } from "react-router";
import { useSession } from "./api/queries";
import { Activity } from "./pages/activity/Activity";
import { Agents } from "./pages/agents/Agents";
import { Building } from "./pages/Building";
import { Dashboard } from "./pages/dashboard/Dashboard";
import { NotFound } from "./pages/NotFound";
import { OptionChain } from "./pages/options/OptionChain";
import { Orders } from "./pages/orders/Orders";
import { Positions } from "./pages/positions/Positions";
import { SignIn } from "./pages/SignIn";
import { Script } from "./pages/scripts/Script";
import { Scripts } from "./pages/scripts/Scripts";
import { Settings } from "./pages/settings/Settings";
import { Strategies } from "./pages/strategies/Strategies";
import { Strategy } from "./pages/strategy/Strategy";
import { SymbolPage } from "./pages/symbol/Symbol";
import { Trades } from "./pages/trades/Trades";
import { WatchlistPage } from "./pages/watchlist/Watchlist";
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
  "/": <Dashboard />,
  "/watchlist": <WatchlistPage />,
  "/options": <OptionChain />,
  "/positions": <Positions />,
  "/orders": <Orders />,
  "/trades": <Trades />,
  "/strategies": <Strategies />,
  "/scripts": <Scripts />,
  "/agents": <Agents />,
  "/activity": <Activity />,
  "/settings": <Settings />,
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
          { path: "/scripts/:id", element: <Script /> },
          { path: "/symbols/:exchange/:symbol", element: <SymbolPage /> },
          { path: "/options/:exchange/:underlying", element: <OptionChain /> },
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
]);

export function App() {
  return <RouterProvider router={router} />;
}
