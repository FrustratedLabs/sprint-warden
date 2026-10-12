// Tiny shopping cart for the sprintwarden Vitest example. Amounts are in cents.

// Sprint S01: totals.
export function total(lines) {
  return lines.reduce((sum, line) => sum + line.cents * line.qty, 0);
}

// Sprint S02: percentage coupons, rounded half-up to the cent.
export function applyCoupon(cents, coupon, today = new Date()) {
  if (coupon.expires && new Date(coupon.expires) < today) throw new Error("coupon expired");
  return cents - Math.round((cents * coupon.percent) / 100);
}

export const VERSION = "1.0.0";
