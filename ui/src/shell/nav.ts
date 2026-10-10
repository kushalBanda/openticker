import {
  ArrowLeftRight,
  Bot,
  Brain,
  FileCode2,
  Layers,
  LayoutDashboard,
  List,
  type LucideIcon,
  Receipt,
  ScrollText,
  Settings,
  Wallet,
  Workflow,
} from "lucide-react";

export interface NavPage {
  path: string;
  label: string;
  icon: LucideIcon;
  key: string; // pressed after "g"
}

// The sidebar's pages, in DESIGN.md's order; Settings sits apart at the bottom.
export const PAGES: NavPage[] = [
  { path: "/", label: "Dashboard", icon: LayoutDashboard, key: "d" },
  { path: "/watchlist", label: "Watchlist", icon: List, key: "w" },
  { path: "/options", label: "Options", icon: Layers, key: "o" },
  { path: "/positions", label: "Positions", icon: Wallet, key: "p" },
  { path: "/orders", label: "Orders", icon: Receipt, key: "r" },
  { path: "/trades", label: "Trades", icon: ArrowLeftRight, key: "t" },
  { path: "/strategies", label: "Strategies", icon: Workflow, key: "s" },
  { path: "/scripts", label: "Scripts", icon: FileCode2, key: "c" },
  { path: "/brain", label: "Brain", icon: Brain, key: "b" },
  { path: "/agents", label: "Agents", icon: Bot, key: "a" },
  { path: "/activity", label: "Activity", icon: ScrollText, key: "l" },
];

export const SETTINGS: NavPage = { path: "/settings", label: "Settings", icon: Settings, key: "," };
