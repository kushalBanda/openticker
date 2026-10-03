import { Outlet } from "react-router";
import { StreamProvider } from "../stream/StreamProvider";
import { ActionsProvider } from "./actions";
import { Banners } from "./Banners";
import { EventsProvider } from "./events";
import { Sidebar } from "./Sidebar";
import { StatusBar } from "./StatusBar";
import { useTabStatus } from "./TabStatus";
import { BarTitleProvider } from "./title";
import { ToastProvider } from "./toasts";

function TabStatus() {
  useTabStatus();
  return null;
}

export function AppShell() {
  return (
    <StreamProvider>
      <BarTitleProvider>
        <ToastProvider>
          <EventsProvider>
            <ActionsProvider>
              <TabStatus />
              <div className="app">
                <Sidebar />
                <StatusBar />
                <Banners />
                <Outlet />
              </div>
            </ActionsProvider>
          </EventsProvider>
        </ToastProvider>
      </BarTitleProvider>
    </StreamProvider>
  );
}
