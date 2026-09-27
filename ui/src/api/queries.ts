import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
