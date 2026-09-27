import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, type Schemas, unwrap } from "./client";

export const keys = {
  session: ["session"] as const,
  positions: (broker: string, includeClosed: boolean) =>
    ["positions", broker, includeClosed] as const,
  funds: (broker: string) => ["funds", broker] as const,
  quote: (broker: string, exchange: string, symbol: string) =>
    ["quote", broker, exchange, symbol] as const,
  charges: (params: ChargesParams) => ["charges", params] as const,
  orders: (broker: string) => ["orders", broker] as const,
  trades: (broker: string, period: Period) => ["trades", broker, period] as const,
  margin: (params: MarginParams) => ["margin", params] as const,
  search: (query: string) => ["search", query] as const,
  listings: (symbol: string) => ["listings", symbol] as const,
  strategies: ["strategies"] as const,
  strategy: (id: string) => ["strategy", id] as const,
  ledger: (id: string) => ["ledger", id] as const,
  signals: (id: string) => ["signals", id] as const,
  reviews: (id: string) => ["reviews", id] as const,
  // Every audit read starts with "audit": a new event refetches them all.
  audit: ["audit"] as const,
  bell: ["audit", "bell"] as const,
  activity: (filter: object) => ["audit", "activity", filter] as const,
  // Settings (ADR 33, ADR 37).
  brokerSession: (broker: string) => ["broker-session", broker] as const,
  instruments: ["instruments-status"] as const,
  apiKeys: ["api-keys"] as const,
  account: ["account"] as const,
  notifications: ["notifications"] as const,
  health: ["health"] as const,
  // Dashboard (ADR 34).
  today: (broker: string) => ["today", broker] as const,
  setup: (broker: string) => ["setup", broker] as const,
  pnlHistory: (broker: string, from: string, to: string) =>
    ["pnl-history", broker, from, to] as const,
  chargesSummary: (from: string, to: string) => ["charges-summary", from, to] as const,
  // Symbol.
  bars: (broker: string, exchange: string, symbol: string, interval: string, from: string) =>
    ["bars", broker, exchange, symbol, interval, from] as const,
  depth: (broker: string, exchange: string, symbol: string) =>
    ["depth", broker, exchange, symbol] as const,
  // Watchlists (ADR 36).
  watchlists: ["watchlists"] as const,
  quotes: (broker: string, instruments: string) => ["quotes", broker, instruments] as const,
  // Option chain (ADR 38).
  chain: (broker: string, exchange: string, underlying: string, expiry: string, strikes: number) =>
    ["option-chain", broker, exchange, underlying, expiry, strikes] as const,
  payoff: (broker: string, legs: string) => ["payoff", broker, legs] as const,
  basketMargin: (broker: string, orders: string) => ["basket-margin", broker, orders] as const,
  basketCharges: (orders: string) => ["basket-charges", orders] as const,
  // Scripts (ADR 25) and agents (ADR 29, ADR 35).
  scripts: ["scripts"] as const,
  script: (id: string) => ["script", id] as const,
  scriptSource: (id: string, sha: string) => ["script-source", id, sha] as const,
  scriptLogs: (id: string, runId: string) => ["script-logs", id, runId] as const,
  agents: ["agents"] as const,
  agentJobs: ["agent-jobs"] as const,
  agentJobLog: (id: string) => ["agent-job-log", id] as const,
};

// Positions and funds refetch every 30 s; the page marks them to market
// with every tick in between (ADR 32).
const REFETCH_MS = 30_000;

/** This browser's session, or null when it isn't signed in. */
export function useSession() {
  return useQuery({
    queryKey: keys.session,
    queryFn: async (): Promise<Schemas["SessionResult"] | null> => {
      try {
        return await unwrap(api.GET("/api/v1/session"));
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
    staleTime: 5 * 60_000,
    retry: (count, error) => !(error instanceof ApiError) && count < 3,
  });
}

export function useSignOut(everywhere: boolean) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      everywhere
        ? unwrap(api.POST("/api/v1/session/sign-out-all"))
        : unwrap(api.POST("/api/v1/session/sign-out")),
    onSettled: () => client.setQueryData(keys.session, null),
  });
}

export type Position = Schemas["PositionResult"];
export type Holder = Schemas["HolderResult"];
type Exchange = Schemas["Exchange"];

export function usePositions(broker: string | undefined, includeClosed: boolean) {
  return useQuery({
    queryKey: keys.positions(broker ?? "", includeClosed),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/positions", {
          params: { query: { broker: broker ?? "", include_closed: includeClosed } },
        }),
      ),
    enabled: broker !== undefined,
    refetchInterval: REFETCH_MS,
  });
}

export function useFunds(broker: string | undefined) {
  return useQuery({
    queryKey: keys.funds(broker ?? ""),
    queryFn: () =>
      unwrap(api.GET("/api/v1/funds", { params: { query: { broker: broker ?? "" } } })),
    enabled: broker !== undefined,
    refetchInterval: REFETCH_MS,
  });
}

/** One instrument's quote, with bid and ask. */
export function useQuote(broker: string | undefined, exchange: Exchange, symbol: string) {
  return useQuery({
    queryKey: keys.quote(broker ?? "", exchange, symbol),
    queryFn: async () => {
      const result = await unwrap(
        api.POST("/api/v1/quotes", {
          body: { broker: broker ?? "", instruments: [{ exchange, symbol }] },
        }),
      );
      return result.quotes[0] ?? null;
    },
    enabled: broker !== undefined,
    staleTime: 2_000,
  });
}

export interface ChargesParams {
  symbol: string;
  exchange: Exchange;
  side: "BUY" | "SELL";
  quantity: number;
  price: number;
  product: Schemas["Product"];
}

/** What one paper fill would pay, at the rates the sandbox charges. */
export function useChargesPreview(params: ChargesParams | null) {
  return useQuery({
    queryKey: keys.charges(params ?? ({} as ChargesParams)),
    queryFn: () =>
      unwrap(api.GET("/api/v1/charges/preview", { params: { query: params as ChargesParams } })),
    enabled: params !== null && params.quantity > 0 && params.price > 0,
    staleTime: 60_000,
  });
}

export interface MarginParams {
  broker: string;
  symbol: string;
  exchange: Exchange;
  side: "BUY" | "SELL";
  quantity: number;
  product: Schemas["Product"];
  price: number;
}

/** What the paper account would block for an order, by the sandbox's own rule. */
export function usePaperMargin(params: MarginParams | null) {
  return useQuery({
    queryKey: keys.margin(params ?? ({} as MarginParams)),
    queryFn: () =>
      unwrap(api.GET("/api/v1/margin/paper", { params: { query: params as MarginParams } })),
    enabled: params !== null && params.quantity > 0 && params.price > 0,
    staleTime: 5_000,
    placeholderData: (previous) => previous,
  });
}

export type Instrument = Schemas["InstrumentResult"];

/** Instruments whose symbol starts with `query`, from the local master. */
export function useInstrumentSearch(query: string) {
  const wanted = query.trim().toUpperCase();
  return useQuery({
    queryKey: keys.search(wanted),
    queryFn: () =>
      unwrap(api.GET("/api/v1/instruments", { params: { query: { query: wanted, limit: 8 } } })),
    enabled: wanted.length > 0,
    staleTime: 60_000,
    placeholderData: (previous) => previous,
  });
}

/** Every listing of one symbol: RELIANCE on NSE and BSE; a contract on its one exchange. */
export function useListings(symbol: string) {
  return useQuery({
    queryKey: keys.listings(symbol),
    queryFn: async () => {
      const found = await unwrap(
        api.GET("/api/v1/instruments", { params: { query: { query: symbol, limit: 10 } } }),
      );
      return found.instruments.filter((instrument) => instrument.symbol === symbol);
    },
    staleTime: 5 * 60_000,
  });
}

/** Today's orders, newest first. Resting ones fill in the server: refetched every 5 s. */
export function useOrders(broker: string | undefined) {
  return useQuery({
    queryKey: keys.orders(broker ?? ""),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/orders", {
          params: { query: { broker: broker ?? "", limit: 200, today_only: true } },
        }),
      ),
    enabled: broker !== undefined,
    refetchInterval: 5_000,
  });
}

export type Trade = Schemas["TradeResult"];
export type Period = "today" | "week" | "month";

/** Fills since the start of the period, newest first; resting orders fill in the server. */
export function useTrades(broker: string | undefined, period: Period) {
  return useQuery({
    queryKey: keys.trades(broker ?? "", period),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/trades", {
          params: { query: { broker: broker ?? "", limit: 500, period } },
        }),
      ),
    enabled: broker !== undefined,
    refetchInterval: 5_000,
  });
}

/** After anything that moves positions or orders: refetch them and the funds. */
function useRefreshAccount() {
  const client = useQueryClient();
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: ["positions"] }),
      client.invalidateQueries({ queryKey: ["funds"] }),
      client.invalidateQueries({ queryKey: ["orders"] }),
      client.invalidateQueries({ queryKey: ["trades"] }),
      client.invalidateQueries({ queryKey: ["margin"] }),
    ]);
}

export function usePlaceOrder() {
  const refresh = useRefreshAccount();
  return useMutation({
    mutationFn: (body: Schemas["PlaceOrderBody"]) => unwrap(api.POST("/api/v1/orders", { body })),
    onSettled: refresh,
  });
}

export function useModifyOrder() {
  const refresh = useRefreshAccount();
  return useMutation({
    mutationFn: ({ orderId, ...body }: Schemas["ModifyOrderBody"] & { orderId: string }) =>
      unwrap(
        api.PATCH("/api/v1/orders/{order_id}", { params: { path: { order_id: orderId } }, body }),
      ),
    onSettled: refresh,
  });
}

export function useCancelOrder() {
  const refresh = useRefreshAccount();
  return useMutation({
    mutationFn: ({ orderId, broker }: { orderId: string; broker: string }) =>
      unwrap(
        api.DELETE("/api/v1/orders/{order_id}", {
          params: { path: { order_id: orderId }, query: { broker } },
        }),
      ),
    onSettled: refresh,
  });
}

export function useCancelAll() {
  const refresh = useRefreshAccount();
  return useMutation({
    mutationFn: (broker: string) =>
      unwrap(api.POST("/api/v1/orders/cancel-all", { body: { broker } })),
    onSettled: refresh,
  });
}

export function useClosePosition() {
  const refresh = useRefreshAccount();
  return useMutation({
    mutationFn: (body: Schemas["ClosePositionBody"]) =>
      unwrap(api.POST("/api/v1/positions/close", { body })),
    onSettled: refresh,
  });
}

export function useCloseAll() {
  const refresh = useRefreshAccount();
  return useMutation({
    mutationFn: (broker: string) =>
      unwrap(api.POST("/api/v1/positions/close-all", { body: { broker } })),
    onSettled: refresh,
  });
}

/** Every strategy with what it is doing now; the daemon moves them, so refetched every 5 s. */
export function useStrategies() {
  return useQuery({
    queryKey: keys.strategies,
    queryFn: () => unwrap(api.GET("/api/v1/strategies")),
    refetchInterval: 5_000,
  });
}

/** One strategy's definition. */
export function useStrategy(id: string) {
  return useQuery({
    queryKey: keys.strategy(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/strategies/{strategy_id}", { params: { path: { strategy_id: id } } }),
      ),
    staleTime: 60_000,
  });
}

/** Totals and equity after costs, and the newest 50 runs with their fills. */
export function useLedger(id: string) {
  return useQuery({
    queryKey: keys.ledger(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/strategies/{strategy_id}/ledger", {
          params: { path: { strategy_id: id }, query: { limit: 50 } },
        }),
      ),
    refetchInterval: 30_000,
  });
}

/** A signal strategy's alerts, newest first. */
export function useSignals(id: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.signals(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/strategies/{strategy_id}/signals", {
          params: { path: { strategy_id: id }, query: { limit: 100 } },
        }),
      ),
    enabled,
    refetchInterval: 5_000,
  });
}

/** Its review jobs, newest first; one may be running. */
export function useReviews(id: string) {
  return useQuery({
    queryKey: keys.reviews(id),
    queryFn: () =>
      unwrap(api.GET("/api/v1/agent-jobs", { params: { query: { strategy_id: id, limit: 50 } } })),
    refetchInterval: 10_000,
  });
}

/** After a strategy command: refetch the strategies at once and again when the daemon has acted. */
function useRefreshStrategies() {
  const client = useQueryClient();
  const refreshAccount = useRefreshAccount();
  return () => {
    const again = () =>
      Promise.all([
        client.invalidateQueries({ queryKey: keys.strategies }),
        client.invalidateQueries({ queryKey: ["strategy"] }),
        client.invalidateQueries({ queryKey: ["ledger"] }),
        client.invalidateQueries({ queryKey: ["signals"] }),
        client.invalidateQueries({ queryKey: ["reviews"] }),
        client.invalidateQueries({ queryKey: keys.agentJobs }),
      ]);
    setTimeout(() => {
      again();
      refreshAccount();
    }, 1_500);
    return again();
  };
}

const path = (id: string) => ({ params: { path: { strategy_id: id } } });

/** Asks a strategy's runner to close legs; it does within about a second. */
export function useCloseStrategyLegs() {
  const refresh = useRefreshStrategies();
  return useMutation({
    mutationFn: async ({ strategyId, legIds }: { strategyId: string; legIds: string[] }) => {
      const commands = [];
      for (const legId of legIds) {
        commands.push(
          await unwrap(
            api.POST("/api/v1/strategies/{strategy_id}/legs/{leg_id}/close", {
              params: { path: { strategy_id: strategyId, leg_id: legId } },
            }),
          ),
        );
      }
      return commands;
    },
    onSettled: refresh,
  });
}

export function useStopStrategy() {
  const refresh = useRefreshStrategies();
  return useMutation({
    mutationFn: (strategyId: string) =>
      unwrap(api.POST("/api/v1/strategies/{strategy_id}/stop", path(strategyId))),
    onSettled: refresh,
  });
}

export function useStartStrategy() {
  const refresh = useRefreshStrategies();
  return useMutation({
    mutationFn: ({ strategyId, broker }: { strategyId: string; broker: string }) =>
      unwrap(
        api.POST("/api/v1/strategies/{strategy_id}/start", {
          ...path(strategyId),
          body: { broker },
        }),
      ),
    onSettled: refresh,
  });
}

export function useKillStrategy() {
  const refresh = useRefreshStrategies();
  return useMutation({
    mutationFn: (strategyId: string) =>
      unwrap(api.POST("/api/v1/strategies/{strategy_id}/kill", path(strategyId))),
    onSettled: refresh,
  });
}

export function useReleaseStrategy() {
  const refresh = useRefreshStrategies();
  return useMutation({
    mutationFn: (strategyId: string) =>
      unwrap(api.POST("/api/v1/strategies/{strategy_id}/release", path(strategyId))),
    onSettled: refresh,
  });
}

/** Scheduled entries on (through `broker`) or off. */
export function useScheduleStrategy() {
  const refresh = useRefreshStrategies();
  return useMutation({
    mutationFn: ({ strategyId, broker }: { strategyId: string; broker: string | null }) =>
      broker === null
        ? unwrap(api.DELETE("/api/v1/strategies/{strategy_id}/schedule", path(strategyId)))
        : unwrap(
            api.POST("/api/v1/strategies/{strategy_id}/schedule", {
              ...path(strategyId),
              body: { broker },
            }),
          ),
    onSettled: refresh,
  });
}

export function useStartReview() {
  const refresh = useRefreshStrategies();
  return useMutation({
    mutationFn: (strategyId: string) =>
      unwrap(api.POST("/api/v1/strategies/{strategy_id}/review", path(strategyId))),
    onSettled: refresh,
  });
}

/** A review schedule, or null to review only when asked. */
export function useReviewSchedule() {
  const refresh = useRefreshStrategies();
  return useMutation({
    mutationFn: ({
      strategyId,
      schedule,
    }: {
      strategyId: string;
      schedule: Schemas["ReviewScheduleDefinition"] | null;
    }) =>
      schedule === null
        ? unwrap(api.DELETE("/api/v1/strategies/{strategy_id}/review-schedule", path(strategyId)))
        : unwrap(
            api.POST("/api/v1/strategies/{strategy_id}/review-schedule", {
              ...path(strategyId),
              body: schedule,
            }),
          ),
    onSettled: refresh,
  });
}

/**
 * A new alert URL; the old one stops working. Its token is in this answer
 * only. Keeps the addresses the old one allowed.
 */
export function useRotateAlertUrl() {
  const refresh = useRefreshStrategies();
  return useMutation({
    mutationFn: ({
      strategyId,
      broker,
      allowedIps,
    }: {
      strategyId: string;
      broker: string;
      allowedIps: string[];
    }) =>
      unwrap(
        api.POST("/api/v1/strategies/{strategy_id}/webhook", {
          ...path(strategyId),
          body: { broker, allowed_ips: allowedIps },
        }),
      ),
    onSettled: refresh,
  });
}

export function useDisableAlertUrl() {
  const refresh = useRefreshStrategies();
  return useMutation({
    mutationFn: (strategyId: string) =>
      unwrap(api.DELETE("/api/v1/strategies/{strategy_id}/webhook", path(strategyId))),
    onSettled: refresh,
  });
}

export type AuditEntry = Schemas["AuditEntryResult"];

interface ActivityFilter {
  eventTypes: string[];
  source: Schemas["Source"] | null;
  fromDate: string;
}

const ACTIVITY_PAGE = 100;

/** The Activity page: newest first, a page at a time; new events refetch it. */
export function useActivity(filter: ActivityFilter) {
  return useInfiniteQuery({
    queryKey: keys.activity(filter),
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/audit", {
          params: {
            query: {
              limit: ACTIVITY_PAGE,
              event_types: filter.eventTypes.length ? filter.eventTypes : undefined,
              source: filter.source ?? undefined,
              from_date: filter.fromDate,
              before_id: pageParam ?? undefined,
            },
          },
        }),
      ),
    initialPageParam: null as number | null,
    getNextPageParam: (last) =>
      last.entries.length < ACTIVITY_PAGE ? null : (last.entries.at(-1)?.id ?? null),
  });
}

/** The bell's last 50: every event but the plain records. */
export function useBell(eventTypes: string[]) {
  return useQuery({
    queryKey: keys.bell,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/audit", { params: { query: { limit: 50, event_types: eventTypes } } }),
      ),
  });
}

// Settings (ADR 33, ADR 37).

export type BrokerSession = Schemas["BrokerSessionResult"];
export type ApiKey = Schemas["ApiKeyResult"];

export function useBrokerSession(broker: string | undefined) {
  return useQuery({
    queryKey: keys.brokerSession(broker ?? ""),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/brokers/{broker}/session", {
          params: { path: { broker: broker ?? "" } },
        }),
      ),
    enabled: broker !== undefined,
  });
}

/** Kite's login page, opened in this tab: it comes back to /brokers/{broker}/callback. */
export function useBrokerLogin() {
  return useMutation({
    mutationFn: async (broker: string) => {
      const found = await unwrap(
        api.GET("/api/v1/brokers/{broker}/login-url", { params: { path: { broker } } }),
      );
      window.location.assign(found.login_url);
    },
  });
}

/** The fallback: the request_token pasted from the URL after login. */
export function useConnectBroker() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["ConnectBody"]) =>
      unwrap(api.POST("/api/v1/brokers/connect", { body })),
    onSettled: () => client.invalidateQueries({ queryKey: ["broker-session"] }),
  });
}

export function useDisconnectBroker() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (broker: string) =>
      unwrap(api.DELETE("/api/v1/brokers/{broker}/session", { params: { path: { broker } } })),
    onSettled: () => client.invalidateQueries({ queryKey: ["broker-session"] }),
  });
}

export function useInstrumentStatus() {
  return useQuery({
    queryKey: keys.instruments,
    queryFn: () => unwrap(api.GET("/api/v1/instruments/status")),
  });
}

export function useSyncInstruments() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (broker: string) =>
      unwrap(api.POST("/api/v1/instruments/sync", { body: { broker } })),
    onSettled: () => client.invalidateQueries({ queryKey: keys.instruments }),
  });
}

export function useApiKeys() {
  return useQuery({
    queryKey: keys.apiKeys,
    queryFn: () => unwrap(api.GET("/api/v1/keys")),
  });
}

export function useCreateKey() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => unwrap(api.POST("/api/v1/keys", { body: { name } })),
    onSettled: () => client.invalidateQueries({ queryKey: keys.apiKeys }),
  });
}

export function useRevokeKey() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      unwrap(api.DELETE("/api/v1/keys/{name}", { params: { path: { name } } })),
    onSettled: () => client.invalidateQueries({ queryKey: keys.apiKeys }),
  });
}

export function useAccount() {
  return useQuery({
    queryKey: keys.account,
    queryFn: () => unwrap(api.GET("/api/v1/account")),
  });
}

/** The full wipe (ADR 37): every page's numbers change, so everything refetches. */
export function useResetAccount() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/account/reset", { body: { confirm: "RESET" } })),
    onSuccess: () => client.invalidateQueries(),
  });
}

export function useCheckCharges() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (broker: string) => unwrap(api.POST("/api/v1/charges/check", { body: { broker } })),
    onSettled: () => client.invalidateQueries({ queryKey: keys.account }),
  });
}

export function useNotifications() {
  return useQuery({
    queryKey: keys.notifications,
    queryFn: () => unwrap(api.GET("/api/v1/notifications")),
    staleTime: Number.POSITIVE_INFINITY, // from .env: changes only with a restart
  });
}

export function useVersion() {
  return useQuery({
    queryKey: keys.health,
    queryFn: () => unwrap(api.GET("/health")),
    staleTime: Number.POSITIVE_INFINITY,
  });
}

// Dashboard (ADR 34).

export type Today = Schemas["TodayResult"];
export type DayPnl = Schemas["DayPnlResult"];

/** The server's figure; the page moves it with ticks in between. */
export function useToday(broker: string | undefined) {
  return useQuery({
    queryKey: keys.today(broker ?? ""),
    queryFn: () =>
      unwrap(api.GET("/api/v1/today", { params: { query: { broker: broker ?? "" } } })),
    enabled: broker !== undefined,
    refetchInterval: 15_000,
  });
}

export function useSetup(broker: string | undefined) {
  return useQuery({
    queryKey: keys.setup(broker ?? ""),
    queryFn: () =>
      unwrap(api.GET("/api/v1/setup", { params: { query: { broker: broker ?? "" } } })),
    enabled: broker !== undefined,
    refetchInterval: (query) => (query.state.data?.done ? false : 5_000),
  });
}

export function usePnlHistory(broker: string | undefined, from: string, to: string) {
  return useQuery({
    queryKey: keys.pnlHistory(broker ?? "", from, to),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/pnl/history", {
          params: { query: { broker: broker ?? "", from_date: from, to_date: to } },
        }),
      ),
    enabled: broker !== undefined,
    staleTime: 60_000,
  });
}

export function useChargesSummary(from: string, to: string) {
  return useQuery({
    queryKey: keys.chargesSummary(from, to),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/charges/summary", { params: { query: { from_date: from, to_date: to } } }),
      ),
    staleTime: 60_000,
  });
}

/** The newest entries of every kind, for the Dashboard's Recent events. */
export function useRecentEvents(limit: number) {
  return useQuery({
    queryKey: [...keys.audit, "recent", limit] as const,
    queryFn: () => unwrap(api.GET("/api/v1/audit", { params: { query: { limit } } })),
  });
}

export type Interval = Schemas["Interval"];
export type Bars = Schemas["BarsResult"];
export type Depth = Schemas["MarketDepthResult"];

/** Candles from `from` to `to` (exchange-local dates), oldest first. Ticks move the last one. */
export function useBars(
  broker: string | undefined,
  exchange: Exchange,
  symbol: string,
  interval: Interval,
  from: string,
  to: string,
) {
  return useQuery({
    queryKey: keys.bars(broker ?? "", exchange, symbol, interval, from),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/bars", {
          params: {
            query: {
              broker: broker ?? "",
              exchange,
              symbol,
              interval,
              start_date: from,
              end_date: to,
              max_bars: 5000,
            },
          },
        }),
      ),
    enabled: broker !== undefined,
    staleTime: 5 * 60_000,
    placeholderData: (previous) => previous,
  });
}

/** Five levels each side and the day so far; the stream carries only the last price, so polled. */
export function useDepth(broker: string | undefined, exchange: Exchange, symbol: string) {
  return useQuery({
    queryKey: keys.depth(broker ?? "", exchange, symbol),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/depth", { params: { query: { broker: broker ?? "", exchange, symbol } } }),
      ),
    enabled: broker !== undefined,
    refetchInterval: 2_000,
  });
}

// Watchlists (ADR 36): shared with agents, so a change from either side
// reaches the other through the audit log (the stream refetches them).

export type Watchlist = Schemas["WatchlistResult"];
export type WatchlistItem = Schemas["WatchlistItemResult"];
export type Quote = Schemas["QuoteResult"];
type InstrumentRef = Schemas["InstrumentRef"];

export function useWatchlists() {
  return useQuery({
    queryKey: keys.watchlists,
    queryFn: () => unwrap(api.GET("/api/v1/watchlists")),
  });
}

/** Quotes for up to 50 instruments (bid, ask, the day's range, volume), every 2 s. */
export function useQuotes(broker: string | undefined, instruments: InstrumentRef[]) {
  const joined = instruments.map((i) => `${i.exchange}:${i.symbol}`).join("|");
  return useQuery({
    queryKey: keys.quotes(broker ?? "", joined),
    queryFn: () =>
      unwrap(api.POST("/api/v1/quotes", { body: { broker: broker ?? "", instruments } })),
    enabled: broker !== undefined && instruments.length > 0,
    refetchInterval: 2_000,
    placeholderData: (previous) => previous,
  });
}

function useWatchlistMutation<V, R>(run: (vars: V) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSettled: () => client.invalidateQueries({ queryKey: keys.watchlists }),
  });
}

export function useCreateWatchlist() {
  return useWatchlistMutation((name: string) =>
    unwrap(api.POST("/api/v1/watchlists", { body: { name } })),
  );
}

export function useRenameWatchlist() {
  return useWatchlistMutation(({ id, name }: { id: string; name: string }) =>
    unwrap(
      api.PATCH("/api/v1/watchlists/{watchlist_id}", {
        params: { path: { watchlist_id: id } },
        body: { name },
      }),
    ),
  );
}

export function useDeleteWatchlist() {
  return useWatchlistMutation((id: string) =>
    unwrap(
      api.DELETE("/api/v1/watchlists/{watchlist_id}", { params: { path: { watchlist_id: id } } }),
    ),
  );
}

export function useWatch() {
  return useWatchlistMutation(
    ({ id, instruments, add }: { id: string; instruments: InstrumentRef[]; add: boolean }) => {
      const options = { params: { path: { watchlist_id: id } }, body: { instruments } };
      return unwrap(
        add
          ? api.POST("/api/v1/watchlists/{watchlist_id}/instruments", options)
          : api.DELETE("/api/v1/watchlists/{watchlist_id}/instruments", options),
      );
    },
  );
}

// Option chain (ADR 38): the chain polled, its basket priced as it changes.

export type Chain = Schemas["OptionChainResult"];
export type ChainQuote = Schemas["OptionQuoteResult"];
export type Payoff = Schemas["PayoffResult"];
type OrderInput = Schemas["OrderInput"];

/**
 * One expiry's chain, `strikes` either side of the money, with the nearest
 * futures, every 3 s: the book and the Greeks come only from quotes, and two
 * calls a poll keep under Kite's quote limit of one a second.
 */
export function useOptionChain(
  broker: string | undefined,
  exchange: Exchange,
  underlying: string,
  expiry: string | undefined,
  strikes: number,
) {
  return useQuery({
    queryKey: keys.chain(broker ?? "", exchange, underlying, expiry ?? "", strikes),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/option-chain", {
          params: {
            query: {
              broker: broker ?? "",
              underlying,
              exchange,
              expiry: expiry ?? null,
              strike_count: strikes,
            },
          },
        }),
      ),
    enabled: broker !== undefined,
    refetchInterval: 3_000,
    retry: false,
    // More strikes of the same chain keep the rows up; another chain starts clean.
    placeholderData: (previous, query) =>
      query?.queryKey[3] === underlying && query.queryKey[4] === (expiry ?? "")
        ? previous
        : undefined,
  });
}

/** A basket's payoff at expiry and today, fetched again when a leg changes. */
export function usePayoff(broker: string | undefined, legs: Schemas["PayoffLegInput"][]) {
  const joined = JSON.stringify(legs);
  return useQuery({
    queryKey: keys.payoff(broker ?? "", joined),
    queryFn: () =>
      unwrap(api.POST("/api/v1/options/payoff", { body: { broker: broker ?? "", legs } })),
    enabled: broker !== undefined && legs.length > 0,
    staleTime: 10_000,
    retry: false,
    placeholderData: (previous) => previous,
  });
}

/** The broker's margin for the whole basket, hedge benefit included (ADR 26). */
export function useBasketMargin(broker: string | undefined, orders: OrderInput[]) {
  return useQuery({
    queryKey: keys.basketMargin(broker ?? "", JSON.stringify(orders)),
    queryFn: () => unwrap(api.POST("/api/v1/margin", { body: { broker: broker ?? "", orders } })),
    enabled: broker !== undefined && orders.length > 0,
    staleTime: 10_000,
    retry: false,
    placeholderData: (previous) => previous,
  });
}

/** What the basket's fills would pay, summed over its orders, at the sandbox's rates. */
export function useBasketCharges(orders: OrderInput[]) {
  return useQuery({
    queryKey: keys.basketCharges(JSON.stringify(orders)),
    queryFn: async () => {
      const each = await Promise.all(
        orders.map((o) =>
          unwrap(
            api.GET("/api/v1/charges/preview", {
              params: {
                query: {
                  symbol: o.symbol,
                  exchange: o.exchange,
                  side: o.side,
                  quantity: o.quantity,
                  price: o.price ?? 0,
                  product: o.product,
                },
              },
            }),
          ),
        ),
      );
      return each.reduce((sum, c) => sum + c.total, 0);
    },
    enabled: orders.length > 0 && orders.every((o) => (o.price ?? 0) > 0),
    staleTime: 60_000,
    retry: false,
    placeholderData: (previous) => previous,
  });
}

export function usePlaceBasket() {
  const refresh = useRefreshAccount();
  return useMutation({
    mutationFn: (body: Schemas["BasketBody"]) =>
      unwrap(api.POST("/api/v1/orders/basket", { body })),
    onSettled: refresh,
  });
}

// Hosted scripts (ADR 25): only the daemon starts and stops them, so a
// command shows once it has acted, within about a second.

export type Script = Schemas["ScriptResult"];
export type ScriptRun = Schemas["ScriptRunResult"];

/** Every script and the limits each run is held to; refetched every 3 s. */
export function useScripts() {
  return useQuery({
    queryKey: keys.scripts,
    queryFn: () => unwrap(api.GET("/api/v1/scripts")),
    refetchInterval: 3_000,
  });
}

const scriptPath = (id: string) => ({ params: { path: { script_id: id } } });

/** One script, its latest 50 runs and start / stop requests. */
export function useScript(id: string) {
  return useQuery({
    queryKey: keys.script(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/scripts/{script_id}", {
          params: { path: { script_id: id }, query: { runs: 50 } },
        }),
      ),
    refetchInterval: 2_000,
  });
}

/** Its source, read once per version (the hash changes with every upload). */
export function useScriptSource(id: string, sha: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: keys.scriptSource(id, sha ?? ""),
    queryFn: async () => {
      const found = await unwrap(
        api.GET("/api/v1/scripts/{script_id}", {
          params: { path: { script_id: id }, query: { runs: 1, include_source: true } },
        }),
      );
      return found.source ?? "";
    },
    enabled: enabled && sha !== undefined,
    staleTime: Number.POSITIVE_INFINITY,
  });
}

/** A run's last 1,000 lines; while it runs, read again every second. */
export function useScriptLogs(id: string, runId: string | undefined, live: boolean) {
  return useQuery({
    queryKey: keys.scriptLogs(id, runId ?? ""),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/scripts/{script_id}/logs", {
          params: { path: { script_id: id }, query: { run_id: runId, lines: 1000 } },
        }),
      ),
    enabled: runId !== undefined,
    refetchInterval: live ? 1_000 : false,
  });
}

function useRefreshScripts() {
  const client = useQueryClient();
  return () => {
    const again = () =>
      Promise.all([
        client.invalidateQueries({ queryKey: keys.scripts }),
        client.invalidateQueries({ queryKey: ["script"] }),
        client.invalidateQueries({ queryKey: ["script-logs"] }),
      ]);
    setTimeout(again, 1_200);
    return again();
  };
}

export function useStartScript() {
  const refresh = useRefreshScripts();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.POST("/api/v1/scripts/{script_id}/start", scriptPath(id))),
    onSettled: refresh,
  });
}

export function useStopScript() {
  const refresh = useRefreshScripts();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.POST("/api/v1/scripts/{script_id}/stop", scriptPath(id))),
    onSettled: refresh,
  });
}

/** A schedule, or null to run it only when started. */
export function useScheduleScript() {
  const refresh = useRefreshScripts();
  return useMutation({
    mutationFn: ({
      id,
      schedule,
    }: {
      id: string;
      schedule: Schemas["ScriptScheduleDefinition"] | null;
    }) =>
      schedule === null
        ? unwrap(api.DELETE("/api/v1/scripts/{script_id}/schedule", scriptPath(id)))
        : unwrap(
            api.POST("/api/v1/scripts/{script_id}/schedule", { ...scriptPath(id), body: schedule }),
          ),
    onSettled: refresh,
  });
}

// Agents: the MCP clients seen (ADR 35) and review jobs (ADR 29).

export type AgentJob = Schemas["AgentJobResult"];

export function useAgents() {
  return useQuery({
    queryKey: keys.agents,
    queryFn: () => unwrap(api.GET("/api/v1/agents")),
    refetchInterval: 10_000,
  });
}

/** Every strategy's jobs, newest 50; refetched every 3 s while one waits or runs. */
export function useAgentJobs() {
  return useQuery({
    queryKey: keys.agentJobs,
    queryFn: () => unwrap(api.GET("/api/v1/agent-jobs", { params: { query: { limit: 50 } } })),
    refetchInterval: (query) =>
      query.state.data?.jobs.some((j) => j.status !== "ended") ? 3_000 : 15_000,
  });
}

export function useAgentJobLog(id: string | null) {
  return useQuery({
    queryKey: keys.agentJobLog(id ?? ""),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/agent-jobs/{job_id}/log", { params: { path: { job_id: id ?? "" } } }),
      ),
    enabled: id !== null,
    refetchInterval: 2_000,
  });
}

export function useStopAgentJob() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.POST("/api/v1/agent-jobs/{job_id}/stop", { params: { path: { job_id: id } } })),
    onSettled: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: keys.agentJobs }),
        client.invalidateQueries({ queryKey: keys.agents }),
        client.invalidateQueries({ queryKey: ["reviews"] }),
      ]),
  });
}
