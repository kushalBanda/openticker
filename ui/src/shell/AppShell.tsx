import { Outlet } from "react-router";
import { StreamProvider } from "../stream/StreamProvider";
import { Sidebar } from "./Sidebar";
import { StatusBar } from "./StatusBar";
import { BarTitleProvider } from "./title";

export function AppShell() {
  return (
    <StreamProvider>
      <BarTitleProvider>
        <div className="app">
          <Sidebar />
          <StatusBar />
          <div className="banners" />
          <Outlet />
        </div>
      </BarTitleProvider>
    </StreamProvider>
  );
}
