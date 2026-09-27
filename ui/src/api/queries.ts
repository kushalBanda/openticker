import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, type Schemas, unwrap } from "./client";

export const keys = {
  session: ["session"] as const,
};

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
