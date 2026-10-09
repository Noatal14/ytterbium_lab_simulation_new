export const text = (value: unknown): value is string => typeof value === "string";
export const exactKeys = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));
export const finiteNonnegative = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0;
export const boundedPrintable = (value: unknown, limit: number): value is string => text(value) && value.length <= limit && !/[\u0000-\u001f\u007f]/.test(value);
export const nullableBoundedPrintable = (value: unknown, limit: number): value is string | null => value === null || boundedPrintable(value, limit);
export function validUtc(value: unknown) { return text(value) && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value) && !Number.isNaN(Date.parse(value)); }
export function roundTiesToEven(value: number) { const lower = Math.floor(value); const fraction = value - lower; const tolerance = Number.EPSILON * Math.max(1, Math.abs(value)) * 2; if (Math.abs(fraction - 0.5) <= tolerance) return lower % 2 === 0 ? lower : lower + 1; return Math.round(value); }
