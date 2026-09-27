import { createBrowserRouter, Outlet, RouterProvider } from "react-router";
import { useSession } from "./api/queries";
import { Building } from "./pages/Building";
import { NotFound } from "./pages/NotFound";
import { SignIn } from "./pages/SignIn";
import { AppShell } from "./shell/AppShell";
import { PAGES, SETTINGS } from "./shell/nav";

/** Signed in: the app. Not: how to sign in. Unknown yet: the bare ground. */
function Gate() {
  const session = useSession();
  if (session.isPending) return null;
  if (session.data === null) return <SignIn />;
  return <Outlet />;
}

const router = createBrowserRouter([
  {
    element: <Gate />,
    children: [
      {
        element: <AppShell />,
        children: [
          ...[...PAGES, SETTINGS].map((page) => ({
            path: page.path,
            element: <Building title={page.label} />,
          })),
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
]);

export function App() {
  return <RouterProvider router={router} />;
}
