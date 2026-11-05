export type ApiState = "checking" | "ready" | "unavailable";

/** Ask the API whether it can serve requests. A network failure counts as unavailable. */
export async function checkApi(fetcher: typeof fetch = fetch): Promise<ApiState> {
  try {
    const response = await fetcher("/api/ready");
    return response.ok ? "ready" : "unavailable";
  } catch {
    return "unavailable";
  }
}
