import type { Page, Request } from "@playwright/test";

// The specs of this folder run against the built UI with the API intercepted (page.route), so
// they need neither Docker nor a database. A handler is keyed "METHOD /path" (path after
// /normalization, no query string) and answers with a status and a JSON body.
export type Answer = { status?: number; body: unknown };
export type Handlers = Record<string, (request: Request) => Answer>;

export async function stubApi(page: Page, handlers: Handlers): Promise<Request[]> {
  const seen: Request[] = [];
  await page.route("**/normalization/**", async (route) => {
    const request = route.request();
    seen.push(request);
    const path = new URL(request.url()).pathname.replace(/^\/normalization/, "");
    const handler = handlers[`${request.method()} ${path}`];
    const answer = handler ? handler(request) : { status: 404, body: { detail: `no stub for ${request.method()} ${path}` } };
    await route.fulfill({
      status: answer.status ?? 200,
      contentType: "application/json",
      body: JSON.stringify(answer.body),
    });
  });
  return seen;
}
