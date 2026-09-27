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

/** After anything that moves positions: refetch them and the funds. */
function useRefreshAccount() {
  const client = useQueryClient();
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: ["positions"] }),
      client.invalidateQueries({ queryKey: ["funds"] }),
    ]);
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

/** Asks a strategy's runner to close legs; it does within about a second. */
export function useCloseStrategyLegs() {
  const refresh = useRefreshAccount();
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
    onSettled: () => setTimeout(refresh, 1_500),
  });
}

export function useStopStrategy() {
  const refresh = useRefreshAccount();
  return useMutation({
    mutationFn: (strategyId: string) =>
      unwrap(
        api.POST("/api/v1/strategies/{strategy_id}/stop", {
          params: { path: { strategy_id: strategyId } },
        }),
      ),
    onSettled: () => setTimeout(refresh, 1_500),
  });
}
