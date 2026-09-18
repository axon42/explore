import { expect, type APIRequestContext, type Page } from "@playwright/test";
import { selectOption } from "./select";
import type { Detail } from "../src/explore/data";
export type StartedDetail = Detail & { session: NonNullable<Detail["session"]> };
export async function startTest(request: APIRequestContext, mid: string, automatic = true): Promise<StartedDetail> {
  await request.put("/api/settings/test-mode", { data: {enabled:true} });
  const roster = await (await request.get(`/api/meetings/${mid}/participants`)).json();
  const saved = await (await request.put(`/api/meetings/${mid}/participants`, {data:{revision:roster.revision,participants:[{speaker_id:"cofounder",name:"Alex Test",interview_role:"interviewer",job_role:"Cofounder"},{speaker_id:"customer",name:"Sam Test",interview_role:"customer",job_role:"Operations lead"}]}})).json();
  const response = await request.post(`/api/meetings/${mid}/start`, {data:{revision:saved.revision,mode:"test"}});
  expect(response.ok()).toBeTruthy();
  const detail = await response.json();
  if (automatic) {
    const schedule = (await (await request.get(`/api/sessions/${detail.session.id}/experiment`)).json()).scheduling;
    expect((await request.patch(`/api/sessions/${detail.session.id}/analysis-scheduling`, {data:{mode:"automatic",revision:schedule.revision}})).ok()).toBeTruthy();
  }
  return detail;
}
export async function prepareInUI(page:Page, automatic = true) {
  const mode = page.getByRole("switch",{name:"Test mode"});
  if (await mode.getAttribute("aria-checked") !== "true") await mode.click();
  await page.getByRole("button",{name:"Use sample participants",exact:true}).click();
  await expect(page.getByRole("textbox",{name:"Name",exact:true}).first()).toHaveValue("Alex Test");
  await page.getByRole("button",{name:"Start test meeting",exact:true}).click();
  await expect(page.getByRole("button",{name:"End interview",exact:true})).toBeVisible();
  if (automatic) await selectOption(page.getByRole("combobox", {name:"Analysis scheduling"}), "automatic");
}
