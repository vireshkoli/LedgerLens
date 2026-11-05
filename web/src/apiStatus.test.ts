import { describe, expect, it } from "vitest";

import { checkApi } from "./apiStatus";

const respondWith =
  (status: number): typeof fetch =>
  () =>
    Promise.resolve(new Response(null, { status }));

describe("checkApi", () => {
  it("reports ready when the API answers ok", async () => {
    await expect(checkApi(respondWith(200))).resolves.toBe("ready");
  });

  it("reports unavailable when the database is down", async () => {
    await expect(checkApi(respondWith(503))).resolves.toBe("unavailable");
  });

  it("reports unavailable when the request fails", async () => {
    const failing: typeof fetch = () => Promise.reject(new TypeError("network down"));

    await expect(checkApi(failing)).resolves.toBe("unavailable");
  });

  it("calls the proxied ready route", async () => {
    const urls: unknown[] = [];
    const recording: typeof fetch = (input) => {
      urls.push(input);
      return Promise.resolve(new Response(null, { status: 200 }));
    };

    await checkApi(recording);

    expect(urls).toEqual(["/api/ready"]);
  });
});
