import { type ComponentType, lazy, type ReactNode, Suspense, useEffect } from "react";
import { createBrowserRouter, Outlet, RouterProvider } from "react-router";
import { useSession } from "./api/queries";
import { NotFound } from "./pages/NotFound";
import { SignIn } from "./pages/SignIn";
import { AppShell } from "./shell/AppShell";

/** Signed in: the app. Not: how to sign in. Unknown yet: the bare ground. */
function Gate() {
  const session = useSession();
  if (session.isPending) return null;
  if (session.data === null) return <SignIn />;
  return <Outlet />;
}

// Each page is its own chunk, fetched when first opened (ADR 30). Once the
// shell is up, the rest are fetched while the browser is idle, so moving
// between pages never waits on the network.
const loaders: (() => Promise<unknown>)[] = [];
function page<K extends string>(
  load: () => Promise<Record<K, ComponentType>>,
  name: K,
): ComponentType {
  loaders.push(load);
  return lazy(() => load().then((m): { default: ComponentType } => ({ default: m[name] })));
}

const Dashboard = page(() => import("./pages/dashboard/Dashboard"), "Dashboard");
const WatchlistPage = page(() => import("./pages/watchlist/Watchlist"), "WatchlistPage");
const OptionChain = page(() => import("./pages/options/OptionChain"), "OptionChain");
const Positions = page(() => import("./pages/positions/Positions"), "Positions");
const Orders = page(() => import("./pages/orders/Orders"), "Orders");
const Trades = page(() => import("./pages/trades/Trades"), "Trades");
const Strategies = page(() => import("./pages/strategies/Strategies"), "Strategies");
const Strategy = page(() => import("./pages/strategy/Strategy"), "Strategy");
const Scripts = page(() => import("./pages/scripts/Scripts"), "Scripts");
const Script = page(() => import("./pages/scripts/Script"), "Script");
const Agents = page(() => import("./pages/agents/Agents"), "Agents");
const Activity = page(() => import("./pages/activity/Activity"), "Activity");
const Settings = page(() => import("./pages/settings/Settings"), "Settings");
const SymbolPage = page(() => import("./pages/symbol/Symbol"), "SymbolPage");

/** The pages' chunks, fetched in the background once the first page shows. */
function Prefetch() {
  useEffect(() => {
    const idle = window.requestIdleCallback ?? ((fn: () => void) => window.setTimeout(fn, 1500));
    const id = idle(() => {
      for (const load of loaders) load().catch(() => undefined);
    });
    return () => (window.cancelIdleCallback ?? window.clearTimeout)(id);
  }, []);
  return null;
}

// The previous page stays until the next one's chunk arrives (navigations are
// transitions), so this shows only on a first load straight into a page.
function Pages() {
  return (
    <Suspense fallback={null}>
      <Prefetch />
      <Outlet />
    </Suspense>
  );
}

const routes: { path: string; element: ReactNode }[] = [
  { path: "/", element: <Dashboard /> },
  { path: "/watchlist", element: <WatchlistPage /> },
  { path: "/options", element: <OptionChain /> },
  { path: "/options/:exchange/:underlying", element: <OptionChain /> },
  { path: "/positions", element: <Positions /> },
  { path: "/orders", element: <Orders /> },
  { path: "/trades", element: <Trades /> },
  { path: "/strategies", element: <Strategies /> },
  { path: "/strategies/:id", element: <Strategy /> },
  { path: "/scripts", element: <Scripts /> },
  { path: "/scripts/:id", element: <Script /> },
  { path: "/agents", element: <Agents /> },
  { path: "/activity", element: <Activity /> },
  { path: "/settings", element: <Settings /> },
  { path: "/symbols/:exchange/:symbol", element: <SymbolPage /> },
  { path: "*", element: <NotFound /> },
];

const router = createBrowserRouter([
  {
    element: <Gate />,
    children: [{ element: <AppShell />, children: [{ element: <Pages />, children: routes }] }],
  },
]);

export function App() {
  return <RouterProvider router={router} />;
}
