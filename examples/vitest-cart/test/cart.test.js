import { describe, expect, it } from "vitest";
import { VERSION, applyCoupon, total } from "../src/cart.js";

describe("[S01] cart totals", () => {
  it("sums line items", () => {
    expect(total([{ cents: 250, qty: 1 }, { cents: 100, qty: 1 }])).toBe(350);
  });
  it("multiplies by quantity", () => {
    expect(total([{ cents: 250, qty: 3 }])).toBe(750);
  });
});

describe("[S02] coupons", () => {
  it("applies a percentage coupon", () => {
    expect(applyCoupon(1000, { percent: 15 })).toBe(850);
  });
  it("rejects an expired coupon", () => {
    expect(() => applyCoupon(1000, { percent: 10, expires: "2020-01-01" })).toThrow("expired");
  });
});

it("exposes a version", () => {
  expect(VERSION).toMatch(/^\d+\.\d+\.\d+$/);
});
