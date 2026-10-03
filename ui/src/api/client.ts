import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

// Same origin: openticker-serve serves the app and the API; the session cookie
// rides along (ADR 31).
export const api = createClient<paths>({ baseUrl: "", credentials: "same-origin" });

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

/** The body of a successful response; anything else throws an ApiError. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call;
  if (response.ok) return data as T;
  const detail =
    typeof error === "object" && error !== null && "detail" in error
      ? String((error as { detail: unknown }).detail)
      : response.statusText;
  throw new ApiError(response.status, detail);
}

/**
 * Whether a failed query asks again. The server said no (not there, not
 * allowed): asking again won't change it, so the page says so at once. A
 * server or network fault gets two more tries.
 */
export function shouldRetry(failures: number, error: unknown): boolean {
  return !(error instanceof ApiError && error.status < 500) && failures < 2;
}
