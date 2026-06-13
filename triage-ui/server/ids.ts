import { randomBytes } from "node:crypto";

export function newUuid7Hex(): string {
  let timestamp = Date.now();
  const bytes = randomBytes(16);

  for (let index = 5; index >= 0; index -= 1) {
    bytes[index] = timestamp & 0xff;
    timestamp = Math.floor(timestamp / 256);
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x70;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;

  return bytes.toString("hex");
}
