// The plan review screen, against the stubbed API: suggestions render as a
// per-table table with confidence and validated share; "Accept confident"
// ticks only suggestions that pass the confidence/validation bar; Save
// PATCHes exactly the selected columns; a locked plan is read-only.
import { expect, test, type Page } from "@playwright/test";
import type { Answer, Handlers } from "./stub-api";

const PLAN_PENDING = {
  job_id: "job-plan",
  status: "PENDING_DB_CREATE",
  amendable: true,
  tables: [
    {
      table: "company",
      destination_table: "company",
      key_columns: ["id"],
      extra_columns: {},
      columns: [
        {
          column: "company_name",
          source_type: "text",
          semantic_type: null,
          decided_by: null,
          suggestion: {
            semantic_type: "COMPANY_NAME",
            confidence: 0.9,
            validated_share: 1.0,
            sampled: 200,
            reason: "field name matches a company-name pattern",
          },
          destination_type: null,
          companion_column: null,
        },
        {
          column: "taxonomy_like",
          source_type: "text",
          semantic_type: null,
          decided_by: null,
          suggestion: {
            semantic_type: "PERSON_NAME",
            confidence: 0.8,
            validated_share: 0.25,
            sampled: 4,
            reason: "field name matches a name pattern",
          },
          destination_type: null,
          companion_column: null,
        },
        {
          column: "description",
          source_type: "text",
          semantic_type: null,
          decided_by: null,
          suggestion: null,
          destination_type: null,
          companion_column: null,
        },
      ],
    },
  ],
};

function handlers(patchAnswer: Answer): Handlers {
  return {
    "GET /clone-jobs/job-plan": () => ({
      body: { job_id: "job-plan", status: "PENDING_DB_CREATE", tables: ["company"] },
    }),
    "GET /clone-jobs/job-plan/plan": () => ({ body: PLAN_PENDING }),
    "PATCH /clone-jobs/job-plan/plan": (request) => {
      // Fill the caller's body object in place: `sent` must observe it.
      Object.assign(patchAnswer.body as object, JSON.parse(request.postData() ?? "{}"));
      return patchAnswer;
    },
  };
}

async function openPlan(page: Page, patchAnswer: Answer) {
  await page.route("**/normalization/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/normalization/, "");
    const h = handlers(patchAnswer)[`${request.method()} ${path}`];
    const answer = h ? h(request) : { status: 404, body: { detail: `no stub ${path}` } };
    await route.fulfill({
      status: answer.status ?? 200,
      contentType: "application/json",
      body: JSON.stringify(answer.body),
    });
  });
  await page.goto("/#/jobs/job-plan/plan");
}

test("suggestions show with confidence, validated share and reason; unsuggested columns stay out", async ({ page }) => {
  await openPlan(page, { body: {} });
  await expect(page.getByRole("cell", { name: "COMPANY_NAME", exact: true })).toBeVisible();
  await expect(page.getByText("100% of 200")).toBeVisible();
  await expect(page.getByText("field name matches a company-name pattern")).toBeVisible();
  // `description` has no suggestion and must not appear as a row here.
  await expect(page.getByRole("checkbox", { name: /company\.description/ })).toHaveCount(0);
});

test("accept confident ticks the 0.9 suggestion and leaves the contradicted 0.8 one", async ({ page }) => {
  await openPlan(page, { body: {} });
  await page.getByTestId("accept-confident").click();
  await expect(page.getByRole("checkbox", { name: "Accept COMPANY_NAME for company.company_name" })).toBeChecked();
  await expect(
    page.getByRole("checkbox", { name: "Accept PERSON_NAME for company.taxonomy_like" }),
  ).not.toBeChecked();
  await expect(page.getByTestId("selected-count")).toHaveText("1 selected");
});

test("Save sends PATCH with exactly the selected table/columns", async ({ page }) => {
  const sent: Record<string, unknown> = {};
  await openPlan(page, { body: sent });
  await page.getByRole("checkbox", { name: "Accept COMPANY_NAME for company.company_name" }).check();
  await page.getByTestId("save-plan").click();
  await expect(page.getByTestId("plan-saved")).toBeVisible();
  await expect.poll(() => JSON.stringify(sent)).toBe(
    JSON.stringify({ field_configs: { company: { company_name: "COMPANY_NAME" } } }),
  );
});

test("a save the API refuses (plan locked meanwhile) shows its message", async ({ page }) => {
  await openPlan(page, { status: 409, body: { detail: "plan can only be amended while PENDING_DB_CREATE" } });
  await page.getByRole("checkbox", { name: "Accept COMPANY_NAME for company.company_name" }).check();
  await page.getByTestId("save-plan").click();
  await expect(page.getByText("plan can only be amended while PENDING_DB_CREATE")).toBeVisible();
});
