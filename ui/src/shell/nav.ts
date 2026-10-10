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
  /** Other pages this item stands for: its tabs. */
  also?: string[];
}

// The sidebar's pages, in DESIGN.md's order; Settings sits apart at the bottom.
export const PAGES: NavPage[] = [
  { path: "/", label: "Dashboard", icon: LayoutDashboard },
  { path: "/watchlist", label: "Watchlist", icon: List },
  { path: "/options", label: "Options", icon: Layers },
  { path: "/positions", label: "Portfolio", icon: Wallet, also: ["/orders", "/trades"] },
  { path: "/strategies", label: "Strategies", icon: Workflow },
  { path: "/scripts", label: "Scripts", icon: FileCode2 },
  { path: "/brain", label: "Brain", icon: Brain },
  { path: "/agents", label: "Agents", icon: Bot },
  { path: "/activity", label: "Activity", icon: ScrollText },
];

// Portfolio's tabs: one sidebar item, three pages with their own addresses.
export const PORTFOLIO: NavPage[] = [
  { path: "/positions", label: "Positions", icon: Wallet },
  { path: "/orders", label: "Orders", icon: Receipt },
  { path: "/trades", label: "Trades", icon: ArrowLeftRight },
];

export const SETTINGS: NavPage = { path: "/settings", label: "Settings", icon: Settings };

/** Every page one can go to by name: the sidebar's, with Portfolio as its tabs. */
export const DESTINATIONS: NavPage[] = [
  ...PAGES.flatMap((page) => (page.also ? PORTFOLIO : [page])),
  SETTINGS,
];
