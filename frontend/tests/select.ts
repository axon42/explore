import { expect, type Locator } from "@playwright/test";

/** Exercise the visible combobox and option, including menus portaled out of forms. */
export async function selectOption(control: Locator, value: string) {
  await control.click();
  const option = control.page().getByRole("option").and(control.page().locator(`[data-value=${JSON.stringify(value)}]`));
  await option.click();
  await expect(control).toHaveAttribute("data-value", value);
}
