const rightRotate = (value: number, amount: number): number =>
  (value >>> amount) | (value << (32 - amount));

export const canonicalJson = (value: unknown): string => {
  const compareUnicodeCodePoints = (left: string, right: string): number => {
    const leftPoints = Array.from(left, (character) => character.codePointAt(0) ?? 0);
    const rightPoints = Array.from(right, (character) => character.codePointAt(0) ?? 0);
    const length = Math.min(leftPoints.length, rightPoints.length);
    for (let index = 0; index < length; index++) {
      if (leftPoints[index] !== rightPoints[index]) {
        return leftPoints[index] - rightPoints[index];
      }
    }
    return leftPoints.length - rightPoints.length;
  };
  const normalize = (item: unknown): unknown => {
    if (item === null || typeof item === "string" || typeof item === "boolean") {
      return item;
    }
    if (typeof item === "number") {
      if (!Number.isFinite(item)) {
        throw new Error("Canonical JSON cannot contain non-finite numbers");
      }
      return item;
    }
    if (Array.isArray(item)) {
      return item.map(normalize);
    }
    if (typeof item === "object") {
      return Object.fromEntries(
        Object.entries(item as Record<string, unknown>)
          .sort(([left], [right]) => compareUnicodeCodePoints(left, right))
          .map(([key, child]) => [key, normalize(child)]),
      );
    }
    throw new Error(`Canonical JSON cannot contain ${typeof item}`);
  };
  return JSON.stringify(normalize(value));
};

// Small synchronous SHA-256 implementation using only browser/Node globals.
// Synchronous hashing lets the Remotion props schema fail before composition
// evaluation without importing Node's crypto module into a browser bundle.
export const sha256Hex = (text: string): string => {
  const bytes = new TextEncoder().encode(text);
  const bitLength = bytes.length * 8;
  const paddedLength = Math.ceil((bytes.length + 9) / 64) * 64;
  const padded = new Uint8Array(paddedLength);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const view = new DataView(padded.buffer);
  const highBits = Math.floor(bitLength / 0x100000000);
  const lowBits = bitLength >>> 0;
  view.setUint32(paddedLength - 8, highBits);
  view.setUint32(paddedLength - 4, lowBits);

  const initial = [
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ];
  const constants = Array.from({length: 64}, (_, index) => {
    let prime = 2;
    let found = 0;
    while (true) {
      let isPrime = true;
      for (let divisor = 2; divisor * divisor <= prime; divisor++) {
        if (prime % divisor === 0) {
          isPrime = false;
          break;
        }
      }
      if (isPrime && found++ === index) {
        return Math.floor((Math.cbrt(prime) % 1) * 0x100000000) >>> 0;
      }
      prime++;
    }
  });
  const hash = initial.slice();
  const words = new Uint32Array(64);
  for (let offset = 0; offset < paddedLength; offset += 64) {
    for (let index = 0; index < 16; index++) {
      words[index] = view.getUint32(offset + index * 4);
    }
    for (let index = 16; index < 64; index++) {
      const left = words[index - 15];
      const right = words[index - 2];
      const sigma0 =
        rightRotate(left, 7) ^ rightRotate(left, 18) ^ (left >>> 3);
      const sigma1 =
        rightRotate(right, 17) ^ rightRotate(right, 19) ^ (right >>> 10);
      words[index] =
        (words[index - 16] + sigma0 + words[index - 7] + sigma1) >>> 0;
    }
    let [a, b, c, d, e, f, g, h] = hash;
    for (let index = 0; index < 64; index++) {
      const sum1 =
        rightRotate(e, 6) ^ rightRotate(e, 11) ^ rightRotate(e, 25);
      const choice = (e & f) ^ (~e & g);
      const temp1 = (h + sum1 + choice + constants[index] + words[index]) >>> 0;
      const sum0 =
        rightRotate(a, 2) ^ rightRotate(a, 13) ^ rightRotate(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (sum0 + majority) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + temp1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temp1 + temp2) >>> 0;
    }
    hash[0] = (hash[0] + a) >>> 0;
    hash[1] = (hash[1] + b) >>> 0;
    hash[2] = (hash[2] + c) >>> 0;
    hash[3] = (hash[3] + d) >>> 0;
    hash[4] = (hash[4] + e) >>> 0;
    hash[5] = (hash[5] + f) >>> 0;
    hash[6] = (hash[6] + g) >>> 0;
    hash[7] = (hash[7] + h) >>> 0;
  }
  return hash.map((value) => value.toString(16).padStart(8, "0")).join("");
};
