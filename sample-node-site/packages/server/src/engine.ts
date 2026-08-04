/**
 * Incremental S/R engine — worker_threads over SharedArrayBuffer ring buffers.
 * The main thread pushes bars into a Float64Array ring; workers scan windows
 * and post level updates back. No COOP/COEP concerns server-side (§S4 workers).
 */
import { Worker } from "node:worker_threads";
import type { Bar } from "./ingest.js";

const RING_SLOTS = 65_536;
const FIELDS = 6; // ts, open, high, low, close, volume

export interface LevelUpdate {
  symbol: string;
  price: number;
  strength: number;
  kind: "support" | "resistance";
}

export class Engine {
  private readonly sab: SharedArrayBuffer;
  private readonly ring: Float64Array;
  private readonly head: Int32Array;
  private readonly workers: Worker[] = [];
  private readonly listeners: Array<(u: LevelUpdate) => void> = [];
  private readonly levelsBySymbol = new Map<string, LevelUpdate[]>();
  private writeIdx = 0;

  constructor(threadCount: number) {
    this.sab = new SharedArrayBuffer(RING_SLOTS * FIELDS * Float64Array.BYTES_PER_ELEMENT);
    this.ring = new Float64Array(this.sab);
    this.head = new Int32Array(new SharedArrayBuffer(4));

    for (let i = 0; i < threadCount; i++) {
      const worker = new Worker(new URL("./sr-worker.js", import.meta.url), {
        workerData: { sab: this.sab, head: this.head.buffer, stride: FIELDS },
      });
      worker.on("message", (update: LevelUpdate) => this.accept(update));
      this.workers.push(worker);
    }
  }

  push(bar: Bar): void {
    const base = (this.writeIdx % RING_SLOTS) * FIELDS;
    this.ring[base] = bar.ts;
    this.ring[base + 1] = bar.open;
    this.ring[base + 2] = bar.high;
    this.ring[base + 3] = bar.low;
    this.ring[base + 4] = bar.close;
    this.ring[base + 5] = bar.volume;
    this.writeIdx += 1;
    Atomics.store(this.head, 0, this.writeIdx);
    Atomics.notify(this.head, 0);
  }

  levels(symbol: string, limit: number): LevelUpdate[] {
    return (this.levelsBySymbol.get(symbol) ?? []).slice(0, limit);
  }

  snapshot(): LevelUpdate[] {
    return [...this.levelsBySymbol.values()].flat();
  }

  onLevelChange(fn: (u: LevelUpdate) => void): void {
    this.listeners.push(fn);
  }

  async stop(): Promise<void> {
    await Promise.all(this.workers.map((w) => w.terminate()));
  }

  private accept(update: LevelUpdate): void {
    const existing = this.levelsBySymbol.get(update.symbol) ?? [];
    this.levelsBySymbol.set(update.symbol, [update, ...existing].slice(0, 500));
    for (const fn of this.listeners) fn(update);
  }
}
